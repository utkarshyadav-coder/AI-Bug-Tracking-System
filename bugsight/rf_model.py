"""
BugSight severity model: a *real* scikit-learn RandomForestClassifier.

The original BugSight prototype (React/TypeScript) only *simulated* a forest
(a weighted sum with random noise). This module replaces it with a trained
forest that you can persist, evaluate, inspect and retrain.

Training data
-------------
Your CSV has no structured impact fields (affected users, frequency, ...), so the
forest is bootstrapped on a synthetic, domain-rule-labelled dataset. As testers /
developers confirm the *actual* severity of reports (``confirmed_severity``),
`retrain()` blends those real labels in with a much higher sample weight.
Until enough real labels exist, treat predictions as a calibrated heuristic, not
ground truth.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split

SEVERITIES = ["Low", "Medium", "High", "Critical"]          # ordered
SEVERITY_VALUE = {s: i + 1 for i, s in enumerate(SEVERITIES)}

BUG_TYPES = {"ui": 2, "logic": 3, "performance": 3, "network": 4,
             "memory_leak": 4, "crash": 5, "security": 5}
COMPONENTS = {"UI": 2, "Dashboard": 2, "Reporting": 2, "Notification": 2, "API": 3,
              "Payment": 4, "Authentication": 5, "Database": 5, "Other": 3}
ENVIRONMENTS = {"development": 1, "staging": 2, "production": 5}
REPRODUCE = {"rare": 1, "sometimes": 3, "immediate": 5}
WORKAROUND = {"yes": 1, "partial": 2, "no": 3}
ERROR_SPIKE = {"<5%": 2, "5-20%": 3, "20-50%": 4, ">50%": 5}

FEATURES = ["bug_type", "component", "environment", "affected_users", "frequency_per_day",
            "time_to_reproduce", "workaround", "error_rate_spike", "stack_depth",
            "days_since_reported"]
FEATURE_LABELS = {
    "bug_type": "Bug type", "component": "Component criticality", "environment": "Environment",
    "affected_users": "Affected users", "frequency_per_day": "Occurrences / day",
    "time_to_reproduce": "Reproducibility", "workaround": "Workaround availability",
    "error_rate_spike": "Error-rate spike", "stack_depth": "Stack-trace depth",
    "days_since_reported": "Days since reported",
}
DEFAULTS = {"bug_type": "logic", "component": "Other", "environment": "development",
            "affected_users": 100, "frequency_per_day": 5, "time_to_reproduce": "sometimes",
            "workaround": "partial", "error_rate_spike": "<5%", "stack_depth": 5,
            "days_since_reported": 0}
_ALIASES = {"type": "bug_type", "bugtype": "bug_type", "affectedusers": "affected_users",
            "frequency": "frequency_per_day", "frequencyperday": "frequency_per_day",
            "timetoreproduce": "time_to_reproduce", "reproducibility": "time_to_reproduce",
            "stackdepth": "stack_depth", "errorratespike": "error_rate_spike",
            "errorspike": "error_rate_spike", "dayssince": "days_since_reported",
            "dayssincereported": "days_since_reported", "env": "environment"}
_NUM_BOUNDS = {"affected_users": (0, 10_000_000), "frequency_per_day": (0, 100_000),
               "stack_depth": (0, 500), "days_since_reported": (0, 3650)}
_COMPONENT_LOOKUP = {k.lower(): k for k in COMPONENTS}
_COMPONENT_LOOKUP.update({"auth": "Authentication", "db": "Database", "frontend": "UI",
                          "core": "Other", "backend": "API"})


def _key(k: str) -> str:
    return "".join(ch for ch in str(k).lower() if ch.isalnum())


def normalize_input(data: dict) -> tuple[dict, list[str]]:
    """Map aliases/camelCase, apply defaults, clamp numbers. Returns (clean, warnings)."""
    warnings: list[str] = []
    raw: dict = {}
    for k, v in (data or {}).items():
        nk = _key(k)
        canon = _ALIASES.get(nk) or next((f for f in FEATURES if _key(f) == nk), None)
        if canon:
            raw[canon] = v
    clean = dict(DEFAULTS)

    def pick(name, table, value):
        v = str(value).strip()
        if name == "component":
            v2 = _COMPONENT_LOOKUP.get(v.lower())
        else:
            v2 = v.lower() if v.lower() in table else (v if v in table else None)
        if v2 is None:
            warnings.append(f"Unknown {name} '{value}', using '{DEFAULTS[name]}'.")
            return DEFAULTS[name]
        return v2

    tables = {"bug_type": BUG_TYPES, "component": COMPONENTS, "environment": ENVIRONMENTS,
              "time_to_reproduce": REPRODUCE, "workaround": WORKAROUND, "error_rate_spike": ERROR_SPIKE}
    for name, table in tables.items():
        if raw.get(name) not in (None, ""):
            clean[name] = pick(name, table, raw[name])
    for name, (lo, hi) in _NUM_BOUNDS.items():
        if raw.get(name) not in (None, ""):
            try:
                clean[name] = int(min(max(float(raw[name]), lo), hi))
            except (TypeError, ValueError):
                warnings.append(f"Invalid {name} '{raw[name]}', using {DEFAULTS[name]}.")
    return clean, warnings


def encode(clean: dict) -> list[float]:
    return [BUG_TYPES[clean["bug_type"]], COMPONENTS[clean["component"]],
            ENVIRONMENTS[clean["environment"]], clean["affected_users"],
            clean["frequency_per_day"], REPRODUCE[clean["time_to_reproduce"]],
            WORKAROUND[clean["workaround"]], ERROR_SPIKE[clean["error_rate_spike"]],
            clean["stack_depth"], clean["days_since_reported"]]


# --------------------------------------------------------------------------
# Synthetic bootstrap data (domain rules + noise)
# --------------------------------------------------------------------------
_WEIGHTS = np.array([1.5, 1.8, 1.4, 2.0, 1.2, 1.0, 1.1, 1.6, 0.8, 0.5])


def synthetic_dataset(n: int = 4000, seed: int = 42) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    bt = rng.choice(list(BUG_TYPES), n)
    comp = rng.choice(list(COMPONENTS), n)
    env = rng.choice(list(ENVIRONMENTS), n, p=[0.30, 0.25, 0.45])
    users = np.clip(rng.lognormal(5.5, 2.0, n), 0, 200_000).astype(int)
    freq = np.clip(rng.lognormal(3.0, 1.5, n), 0, 5000).astype(int)
    rep = rng.choice(list(REPRODUCE), n)
    wa = rng.choice(list(WORKAROUND), n)
    spike = rng.choice(list(ERROR_SPIKE), n, p=[0.4, 0.3, 0.2, 0.1])
    depth = rng.integers(0, 60, n)
    days = rng.integers(0, 90, n)

    X = np.array([[BUG_TYPES[a], COMPONENTS[b], ENVIRONMENTS[c], d, e, REPRODUCE[f],
                   WORKAROUND[g], ERROR_SPIKE[h], i, j]
                  for a, b, c, d, e, f, g, h, i, j in
                  zip(bt, comp, env, users, freq, rep, wa, spike, depth, days)], dtype=float)
    norm = np.column_stack([
        X[:, 0] / 5, X[:, 1] / 5, X[:, 2] / 5,
        np.minimum(np.log10(X[:, 3] + 1) / 4, 1), np.minimum(np.log10(X[:, 4] + 1) / 2.5, 1),
        X[:, 5] / 5, X[:, 6] / 3, X[:, 7] / 5,
        np.minimum(X[:, 8] / 50, 1), np.minimum(X[:, 9] / 30, 1)])
    score = (norm * _WEIGHTS).sum(axis=1) / _WEIGHTS.sum()
    is_prod = X[:, 2] == 5
    score += 0.15 * ((bt == "security") & is_prod) + 0.10 * ((bt == "crash") & is_prod & (users > 1000))
    score -= 0.10 * ((bt == "ui") & (wa == "yes")) + 0.05 * (X[:, 2] == 1)
    score += rng.normal(0, 0.04, n)
    cuts = np.quantile(score, [0.30, 0.62, 0.86])            # ~30/32/24/14 % Low/Med/High/Crit
    y = np.digitize(score, cuts)
    flip = rng.random(n) < 0.04                              # label noise
    y = np.clip(y + flip * rng.choice([-1, 1], n), 0, 3)
    return X, y.astype(int)


# --------------------------------------------------------------------------
class SeverityRF:
    def __init__(self, path: str, n_estimators: int = 150, seed: int = 42):
        self.path = path
        self.meta_path = path.replace(".joblib", ".json")
        self.n_estimators = n_estimators
        self.seed = seed
        self.model: RandomForestClassifier | None = None
        self.meta: dict = {}
        self._lock = threading.Lock()

    # ---- lifecycle
    def ensure_ready(self) -> None:
        with self._lock:
            if self.model is not None:
                return
            if os.path.exists(self.path):
                try:
                    self.model = joblib.load(self.path)
                    if os.path.exists(self.meta_path):
                        with open(self.meta_path) as fh:
                            self.meta = json.load(fh)
                    return
                except Exception as exc:  # corrupt / version mismatch -> retrain
                    print(f"BugSight RF reload failed ({exc}); retraining")
        self.train()

    def train(self, real_rows: list[tuple[list[float], int]] | None = None) -> dict:
        Xs, ys = synthetic_dataset(seed=self.seed)
        Xtr, Xte, ytr, yte = train_test_split(Xs, ys, test_size=0.2, random_state=self.seed, stratify=ys)
        w = np.ones(len(Xtr))
        if real_rows:
            Xr = np.array([r[0] for r in real_rows], dtype=float)
            yr = np.array([r[1] for r in real_rows], dtype=int)
            Xtr = np.vstack([Xtr, Xr]); ytr = np.concatenate([ytr, yr])
            w = np.concatenate([w, np.full(len(yr), 8.0)])
        rf = RandomForestClassifier(n_estimators=self.n_estimators, max_depth=10, min_samples_leaf=3,
                                    class_weight="balanced_subsample", random_state=self.seed, n_jobs=1)
        rf.fit(Xtr, ytr, sample_weight=w)
        pred = rf.predict(Xte)
        meta = {
            "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "n_trees": self.n_estimators, "n_synthetic": int(len(Xs)),
            "n_real": len(real_rows or []),
            "holdout_accuracy": round(float((pred == yte).mean()), 3),
            "holdout_within_one": round(float((abs(pred - yte) <= 1).mean()), 3),
            "label_source": "synthetic bootstrap" + (" + confirmed bugs" if real_rows else ""),
        }
        with self._lock:
            self.model, self.meta = rf, meta
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            joblib.dump(rf, self.path)
            with open(self.meta_path, "w") as fh:
                json.dump(meta, fh)
        return meta

    # ---- inference
    def predict(self, data: dict) -> dict:
        self.ensure_ready()
        clean, warnings = normalize_input(data)
        x = np.array([encode(clean)], dtype=float)
        rf = self.model
        proba = rf.predict_proba(x)[0]
        classes = [int(c) for c in rf.classes_]
        probs = {SEVERITIES[c]: 0.0 for c in range(4)}
        for c, p in zip(classes, proba):
            probs[SEVERITIES[c]] = round(float(p), 4)
        top = max(probs, key=probs.get)
        votes = [classes[int(t.predict(x)[0])] for t in rf.estimators_]
        counts = {s: 0 for s in SEVERITIES}
        for v in votes:
            counts[SEVERITIES[v]] += 1
        expected = sum(probs[s] * SEVERITY_VALUE[s] for s in SEVERITIES)       # 1..4
        imp = sorted(({"feature": f, "label": FEATURE_LABELS[f], "importance": round(float(i), 4)}
                      for f, i in zip(FEATURES, rf.feature_importances_)),
                     key=lambda d: -d["importance"])
        return {"severity": top, "confidence": probs[top], "probabilities": probs,
                "risk_score": round((expected - 1) / 3 * 10, 1), "tree_votes": counts,
                "votes_sample": [SEVERITIES[v] for v in votes[:40]], "n_trees": len(votes),
                "importances": imp, "features": clean, "warnings": warnings}

    def info(self) -> dict:
        self.ensure_ready()
        return {**self.meta, "features": FEATURES}
