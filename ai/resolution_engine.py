"""
AI Resolution Engine
====================
Turns the bug tracker from "classify and store" into "classify, deduplicate,
recommend a fix, and route to the right developer".

Components
----------
KnowledgeBase      TF-IDF index over historical bugs. Finds similar bugs and
                   duplicates, and mines the resolution notes of closed bugs.
ResolutionAdvisor  Combines KnowledgeBase hits into: suggested fixes, ETA,
                   and a ranked list of developers who fixed similar bugs.
LLMFixPlanner      Optional. If ANTHROPIC_API_KEY is set, asks Claude to
                   draft a root-cause hypothesis + fix plan grounded in the
                   similar historical bugs. Silently disabled otherwise.
FallbackSeverity   TF-IDF + logistic regression severity classifier, used when
                   the DistilBERT weights are not present.

Everything works offline with scikit-learn only.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics.pairwise import cosine_similarity

# --------------------------------------------------------------------------
# Tunables
# --------------------------------------------------------------------------
DUPLICATE_THRESHOLD = 0.82   # cosine similarity above which we flag a duplicate
SIMILAR_THRESHOLD = 0.25     # minimum similarity to be shown as "related"
COMPONENT_BOOST = 0.10       # added when the component matches
RESOLVED = ("Closed", "Verified", "Fixed")  # statuses whose notes/times we learn from


def _clean(text: str | None) -> str:
    text = (text or "").lower()
    return re.sub(r"\s+", " ", text).strip()


def _doc(bug: dict) -> str:
    """Text used for indexing a bug. Title is repeated to weight it higher."""
    title = _clean(bug.get("title"))
    return f"{title} {title} {_clean(bug.get('description'))} {_clean(bug.get('component'))}"


# --------------------------------------------------------------------------
# Knowledge base
# --------------------------------------------------------------------------
@dataclass
class SimilarBug:
    bug_id: str
    title: str
    component: str
    status: str
    severity: str
    assigned_to: str | None
    similarity: float
    resolution_notes: str | None = None
    resolution_time: float | None = None
    created: str = ""

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d.pop("created", None)
        d["similarity"] = round(float(self.similarity), 3)
        return d


class KnowledgeBase:
    """TF-IDF index over a list of bug dicts."""

    def __init__(self, bugs: Iterable[dict]):
        self.bugs = [b for b in bugs if b.get("title")]
        self.vectorizer = TfidfVectorizer(
            ngram_range=(1, 2), stop_words="english", sublinear_tf=True, min_df=1
        )
        if self.bugs:
            self.matrix = self.vectorizer.fit_transform([_doc(b) for b in self.bugs])
        else:
            self.matrix = None

    def __len__(self) -> int:
        return len(self.bugs)

    def search(
        self,
        title: str,
        description: str = "",
        component: str | None = None,
        k: int = 5,
        exclude_id: str | None = None,
        only_resolved: bool = False,
        min_similarity: float = SIMILAR_THRESHOLD,
    ) -> list[SimilarBug]:
        if not self.bugs or self.matrix is None:
            return []
        query = _doc({"title": title, "description": description, "component": component})
        scores = cosine_similarity(self.vectorizer.transform([query]), self.matrix)[0]

        results: list[SimilarBug] = []
        for idx in np.argsort(-scores):
            b = self.bugs[idx]
            if exclude_id and b.get("bug_id") == exclude_id:
                continue
            if only_resolved and b.get("status") not in RESOLVED:
                continue
            score = float(scores[idx])
            if component and b.get("component") == component:
                score = min(1.0, score + COMPONENT_BOOST)
            if score < min_similarity:
                continue
            results.append(
                SimilarBug(
                    bug_id=b.get("bug_id"),
                    title=b.get("title"),
                    component=b.get("component"),
                    status=b.get("status"),
                    severity=b.get("severity"),
                    assigned_to=b.get("assigned_to"),
                    similarity=score,
                    resolution_notes=b.get("resolution_notes"),
                    resolution_time=_num(b.get("resolution_time")),
                    created=str(b.get("created_date") or ""),
                )
            )
        # equal similarity -> prefer the most recent bug (newer fixes are more relevant)
        results.sort(key=lambda r: (round(r.similarity, 6), r.created), reverse=True)
        return results[:k]

    def find_duplicates(self, title: str, description: str = "",
                        component: str | None = None) -> list[SimilarBug]:
        """Open or recently-closed bugs that look like the same issue."""
        hits = self.search(title, description, component, k=5,
                           min_similarity=DUPLICATE_THRESHOLD)
        return hits


def _num(v):
    try:
        f = float(v)
        return None if np.isnan(f) else f
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# Resolution advisor
# --------------------------------------------------------------------------
class ResolutionAdvisor:
    """Builds actionable advice for a bug from the historical record."""

    def __init__(self, kb: KnowledgeBase, developer_profiles: dict | None = None):
        self.kb = kb
        self.developer_profiles = developer_profiles or {}

    # ---- fix suggestions -------------------------------------------------
    def suggest_fixes(self, similar: list[SimilarBug], limit: int = 3) -> list[dict]:
        """Rank distinct resolution notes from resolved similar bugs."""
        fixes: dict[str, dict] = {}
        for s in similar:
            note = (s.resolution_notes or "").strip()
            if not note or s.status not in RESOLVED:
                continue
            key = note.lower()
            entry = fixes.setdefault(
                key, {"fix": note, "evidence": [], "score": 0.0}
            )
            entry["evidence"].append(s.bug_id)
            entry["score"] += s.similarity
        ranked = sorted(fixes.values(), key=lambda e: e["score"], reverse=True)[:limit]
        for r in ranked:
            r["score"] = round(r["score"], 3)
            r["seen_in"] = len(r["evidence"])
        return ranked

    # ---- ETA -------------------------------------------------------------
    @staticmethod
    def estimate_eta(similar: list[SimilarBug]) -> dict | None:
        times = [s.resolution_time for s in similar
                 if s.resolution_time and s.status in RESOLVED]
        if not times:
            return None
        weights = [s.similarity for s in similar
                   if s.resolution_time and s.status in RESOLVED]
        mean = float(np.average(times, weights=weights))
        return {
            "expected_days": round(mean, 1),
            "range_days": [round(float(min(times)), 1), round(float(max(times)), 1)],
            "based_on": len(times),
        }

    # ---- who should fix it -----------------------------------------------
    def recommend_developers(
        self,
        similar: list[SimilarBug],
        component: str | None,
        top_n: int = 3,
    ) -> list[dict]:
        """
        Score = 50% evidence from similar bugs they fixed
              + 20% component expertise
              + 15% speed + 15% quality (reopen rate)
              then penalised by current workload.
        """
        evidence = defaultdict(float)
        for s in similar:
            if s.assigned_to and s.status in RESOLVED:
                evidence[s.assigned_to] += s.similarity
        max_ev = max(evidence.values(), default=0.0) or 1.0

        # Only currently-active developers (profiles come from the users table);
        # fall back to evidence-only when no profiles are supplied.
        devs = set(self.developer_profiles) or set(evidence)
        out = []
        for dev in devs:
            p = self.developer_profiles.get(dev, {})
            comp_counts = p.get("component_counts", {})
            total = sum(comp_counts.values()) or 1
            expertise = comp_counts.get(component, 0) / total if component else 0.0

            avg_res = p.get("avg_resolution", 5.0) or 5.0
            speed = max(0.0, 1.0 - min(avg_res, 12.0) / 12.0)
            quality = max(0.0, 1.0 - min(p.get("reopen_rate", 0.1), 0.5) / 0.5)
            workload = p.get("workload", 0)
            load_penalty = min(workload, 8) / 8.0

            score = (
                0.50 * (evidence.get(dev, 0.0) / max_ev)
                + 0.20 * expertise
                + 0.15 * speed
                + 0.15 * quality
            ) * (1.0 - 0.35 * load_penalty)

            reasons = []
            if evidence.get(dev):
                n = sum(1 for s in similar if s.assigned_to == dev
                        and s.status in RESOLVED)
                reasons.append(f"fixed {n} similar bug{'s' if n != 1 else ''}")
            if expertise >= 0.15:
                reasons.append(f"{int(expertise * 100)}% of their work is {component}")
            if speed >= 0.6:
                reasons.append("fast resolver")
            if quality >= 0.8:
                reasons.append("low reopen rate")
            if workload >= 5:
                reasons.append(f"busy ({workload} open)")
            out.append({
                "developer": dev,
                "score": round(score * 100),
                "workload": workload,
                "reasons": reasons or ["general availability"],
            })
        out.sort(key=lambda d: d["score"], reverse=True)
        return out[:top_n]

    # ---- one call to get everything --------------------------------------
    def advise(self, title: str, description: str, component: str | None,
               exclude_id: str | None = None) -> dict:
        # Mine fixes/ETA/developers from every match above the threshold (capped) so a
        # distinct recent fix isn't crowded out by dozens of near-identical old bugs;
        # only the top few are displayed.
        similar = self.kb.search(title, description, component, k=200, exclude_id=exclude_id)
        resolved = [s for s in similar if s.status in RESOLVED]
        dupes = [s for s in similar if s.similarity >= DUPLICATE_THRESHOLD
                 and s.status not in RESOLVED]
        return {
            "duplicates": [d.to_dict() for d in dupes],
            "similar_bugs": [s.to_dict() for s in similar[:5]],
            "suggested_fixes": self.suggest_fixes(resolved),
            "eta": self.estimate_eta(resolved),
            "recommended_developers": self.recommend_developers(resolved, component),
            "confidence": round(float(np.mean([s.similarity for s in resolved[:3]])), 2)
            if resolved else 0.0,
        }


# --------------------------------------------------------------------------
# Optional LLM fix planner
# --------------------------------------------------------------------------
class LLMFixPlanner:
    """
    Drafts a root-cause hypothesis and fix plan with Claude, grounded in the
    similar historical bugs. Requires the `anthropic` package and an
    ANTHROPIC_API_KEY env var; otherwise `available` is False.
    """

    def __init__(self, model: str | None = None):
        self.model = model or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
        self.client = None
        key = os.getenv("ANTHROPIC_API_KEY")
        if key:
            try:
                import anthropic  # type: ignore
                self.client = anthropic.Anthropic(api_key=key)
            except Exception as exc:  # package missing or bad key
                print(f"LLM planner disabled: {exc}")

    @property
    def available(self) -> bool:
        return self.client is not None

    def plan(self, bug: dict, similar: list[dict]) -> dict | None:
        if not self.available:
            return None
        history = "\n".join(
            f"- {s['bug_id']} ({s['component']}, sim={s['similarity']}): {s['title']}"
            + (f" -> fixed by: {s['resolution_notes']}" if s.get("resolution_notes") else "")
            for s in similar[:5]
        ) or "(no similar bugs found)"
        prompt = (
            "You are a senior engineer triaging a bug. Using ONLY the bug and the "
            "historical similar bugs below, reply with a JSON object with keys: "
            '"root_cause_hypotheses" (list of up to 3 strings), "fix_steps" (list of '
            'short strings), "test_plan" (list of short strings), "risk" (one of '
            '"low","medium","high"). No prose outside the JSON.\n\n'
            f"BUG: {bug.get('title')}\nComponent: {bug.get('component')}\n"
            f"Severity: {bug.get('severity')}\nDescription: {bug.get('description')}\n\n"
            f"SIMILAR HISTORICAL BUGS:\n{history}"
        )
        try:
            msg = self.client.messages.create(
                model=self.model,
                max_tokens=800,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
            text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
            return json.loads(text)
        except Exception as exc:
            print(f"LLM planner error: {exc}")
            return None


# --------------------------------------------------------------------------
# Fallback severity classifier (used when DistilBERT weights are missing)
# --------------------------------------------------------------------------
class FallbackSeverity:
    def __init__(self, bugs: Iterable[dict]):
        rows = [b for b in bugs if b.get("severity") and b.get("title")]
        self.ready = len({b["severity"] for b in rows}) >= 2
        if not self.ready:
            return
        self.vec = TfidfVectorizer(ngram_range=(1, 2), stop_words="english", sublinear_tf=True)
        X = self.vec.fit_transform([_doc(b) for b in rows])
        y = [b["severity"] for b in rows]
        self.clf = LogisticRegression(max_iter=1000, class_weight="balanced")
        self.clf.fit(X, y)

    def predict(self, title: str, description: str, component: str | None) -> tuple[str, float]:
        if not self.ready:
            return "Medium", 0.0
        X = self.vec.transform([_doc({"title": title, "description": description,
                                      "component": component})])
        proba = self.clf.predict_proba(X)[0]
        i = int(np.argmax(proba))
        return str(self.clf.classes_[i]), float(proba[i])
