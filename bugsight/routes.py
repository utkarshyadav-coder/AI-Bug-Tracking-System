"""Flask blueprint: BugSight dashboard for Developers and Testers."""
from __future__ import annotations

import io
import json
import os
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import wraps

from flask import Blueprint, Response, jsonify, redirect, render_template, request, session, url_for

from .llm import BugSightClaude
from .rf_model import (BUG_TYPES, COMPONENTS, DEFAULTS, ENVIRONMENTS, ERROR_SPIKE, FEATURES, REPRODUCE,
                       SEVERITIES, WORKAROUND, SeverityRF, encode, normalize_input)

bp = Blueprint("bugsight", __name__)

STATUSES = ["Open", "In Progress", "Resolved", "Closed", "Won't Fix"]
DEV_ROLES = ("developer", "admin", "manager")
ALL_ROLES = ("developer", "tester", "admin", "manager")
MAX_BULK_ROWS = 500

DDL = """
CREATE TABLE IF NOT EXISTS bugsight_reports (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    title               VARCHAR(255) NOT NULL,
    description         TEXT,
    bug_type            VARCHAR(20),
    component           VARCHAR(50),
    environment         VARCHAR(20),
    affected_users      INT,
    frequency_per_day   INT,
    time_to_reproduce   VARCHAR(20),
    workaround          VARCHAR(10),
    error_rate_spike    VARCHAR(10),
    stack_depth         INT,
    days_since_reported INT,
    predicted_severity  VARCHAR(20),
    confidence          FLOAT,
    risk_score          FLOAT,
    probabilities       TEXT,
    status              VARCHAR(20) DEFAULT 'Open',
    confirmed_severity  VARCHAR(20) NULL,
    reporter            VARCHAR(50),
    assigned_to         VARCHAR(50) NULL,
    source              VARCHAR(10) DEFAULT 'manual',
    recommendations     TEXT,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME NULL,
    INDEX idx_bs_status (status),
    INDEX idx_bs_reporter (reporter)
) CHARACTER SET utf8mb4
"""

_state: dict = {}


def _jsonable(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat(sep=" ") if isinstance(v, datetime) else v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return v


def _row(r: dict | None) -> dict | None:
    if r is None:
        return None
    out = {k: _jsonable(v) for k, v in r.items()}
    for k in ("probabilities", "recommendations"):
        if out.get(k):
            try:
                out[k] = json.loads(out[k])
            except (TypeError, ValueError):
                out[k] = None
    return out


def _user():
    return session.get("user")


def require_role(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            u = _user()
            if not u:
                if request.path.startswith("/api/"):
                    return jsonify({"success": False, "error": "Not logged in"}), 401
                return redirect(url_for("login"))
            if u["role"] not in roles:
                return jsonify({"success": False, "error": "Forbidden for your role"}), 403
            return fn(*a, **kw)
        return wrapper
    return deco


def _view_mode(u) -> str:
    """Tester sees the tester module; developers/admin/manager the developer module."""
    if u["role"] == "tester":
        return "tester"
    m = request.args.get("view") or request.values.get("mode")
    return "tester" if (u["role"] in ("admin", "manager") and m == "tester") else "developer"


def _db():
    return _state["get_db"]()


def _fetch(sql, params=()):
    conn = _db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        return rows
    finally:
        conn.close()


def _exec(sql, params=()):
    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        last = getattr(cur, "lastrowid", None)
        n = cur.rowcount
        cur.close()
        return last, n
    finally:
        conn.close()


def _visible_where(u) -> tuple[str, tuple]:
    return ("WHERE reporter = %s", (u["username"],)) if u["role"] == "tester" else ("", ())


def _get_report(rid: int, u) -> dict | None:
    rows = _fetch("SELECT * FROM bugsight_reports WHERE id = %s", (rid,))
    if not rows:
        return None
    if u["role"] == "tester" and rows[0].get("reporter") != u["username"]:
        return None
    return _row(rows[0])


def _save(clean: dict, title: str, desc: str, pred: dict, u, source: str) -> int:
    sql = ("INSERT INTO bugsight_reports (title, description, bug_type, component, environment, affected_users, "
           "frequency_per_day, time_to_reproduce, workaround, error_rate_spike, stack_depth, days_since_reported, "
           "predicted_severity, confidence, risk_score, probabilities, status, reporter, source, created_at) "
           "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'Open',%s,%s,NOW())")
    rid, _ = _exec(sql, (title[:255], desc, clean["bug_type"], clean["component"], clean["environment"],
                         clean["affected_users"], clean["frequency_per_day"], clean["time_to_reproduce"],
                         clean["workaround"], clean["error_rate_spike"], clean["stack_depth"],
                         clean["days_since_reported"], pred["severity"], pred["confidence"], pred["risk_score"],
                         json.dumps(pred["probabilities"]), u["username"], source))
    return rid


def _prediction_from_row(r: dict) -> dict:
    """Re-run the forest on a stored report so the UI always shows fresh importances/votes."""
    pred = _state["rf"].predict(r)
    return pred


def _similar(title, desc, component):
    ga = _state.get("get_advisor")
    if not ga:
        return []
    try:
        return ga().advise(title, desc or "", component)["similar_bugs"]
    except Exception as exc:  # advisor is a nice-to-have grounding source
        print(f"BugSight similar-bug lookup skipped: {exc}")
        return []


# ---------------------------------------------------------------- pages
@bp.get("/bugsight")
@require_role(*ALL_ROLES)
def dashboard():
    u = _user()
    options = {"bug_type": list(BUG_TYPES), "component": list(COMPONENTS), "environment": list(ENVIRONMENTS),
               "time_to_reproduce": list(REPRODUCE), "workaround": list(WORKAROUND),
               "error_rate_spike": list(ERROR_SPIKE)}
    return render_template("bugsight/dashboard.html", user=u, mode=_view_mode(u), options=options,
                           defaults=DEFAULTS, statuses=STATUSES, severities=SEVERITIES,
                           claude_live=_state["claude"].available, claude_model=_state["claude"].model)


# ---------------------------------------------------------------- API
@bp.post("/api/bugsight/predict")
@require_role(*ALL_ROLES)
def api_predict():
    u = _user()
    data = request.get_json(silent=True) or {}
    title = str(data.get("title", "")).strip()
    if not title:
        return jsonify({"success": False, "error": "Title is required"}), 400
    desc = str(data.get("description", "")).strip()[:5000]
    pred = _state["rf"].predict(data)
    rid = None
    if data.get("save", True):
        rid = _save(pred["features"], title, desc, pred, u, "manual")
    return jsonify({"success": True, "id": rid, "prediction": pred})


@bp.post("/api/bugsight/recommend")
@require_role(*ALL_ROLES)
def api_recommend():
    u = _user()
    data = request.get_json(silent=True) or {}
    role = "tester" if (u["role"] == "tester" or (u["role"] in ("admin", "manager") and data.get("mode") == "tester")) else "developer"
    rid = data.get("id")
    if not rid:
        return jsonify({"success": False, "error": "Report id required"}), 400
    r = _get_report(int(rid), u)
    if not r:
        return jsonify({"success": False, "error": "Report not found"}), 404
    cached = r.get("recommendations") or {}
    if cached.get(role) and not data.get("force"):
        return jsonify({"success": True, "cached": True, "recommendation": cached[role]})
    pred = _prediction_from_row(r)
    rec = _state["claude"].recommend(r, pred, role, _similar(r["title"], r["description"], r["component"]))
    if rec["source"] == "claude":      # only cache real LLM output; fallback is cheap to regenerate
        cached[role] = rec
        _exec("UPDATE bugsight_reports SET recommendations = %s, updated_at = NOW() WHERE id = %s",
              (json.dumps(cached), r["id"]))
    return jsonify({"success": True, "cached": False, "recommendation": rec})


@bp.get("/api/bugsight/reports")
@require_role(*ALL_ROLES)
def api_reports():
    u = _user()
    where, params = _visible_where(u)
    rows = [_row(r) for r in _fetch(f"SELECT * FROM bugsight_reports {where} ORDER BY id DESC", params)]
    order = {s: i for i, s in enumerate(reversed(SEVERITIES))}
    if request.args.get("sort") == "severity":
        rows.sort(key=lambda r: (order.get(r["confirmed_severity"] or r["predicted_severity"], 9),
                                 -(r["confidence"] or 0)))
    for r in rows:
        r.pop("recommendations", None)
    return jsonify({"success": True, "reports": rows[:500]})


@bp.get("/api/bugsight/report/<int:rid>")
@require_role(*ALL_ROLES)
def api_report(rid):
    u = _user()
    r = _get_report(rid, u)
    if not r:
        return jsonify({"success": False, "error": "Not found"}), 404
    return jsonify({"success": True, "report": r, "prediction": _prediction_from_row(r)})


@bp.post("/api/bugsight/report/<int:rid>/update")
@require_role(*DEV_ROLES)
def api_update(rid):
    u = _user()
    data = request.get_json(silent=True) or {}
    if not _get_report(rid, u):
        return jsonify({"success": False, "error": "Not found"}), 404
    sets, params = [], []
    if "status" in data:
        if data["status"] not in STATUSES:
            return jsonify({"success": False, "error": "Invalid status"}), 400
        sets.append("status = %s"); params.append(data["status"])
    if "confirmed_severity" in data:
        cs = data["confirmed_severity"] or None
        if cs is not None and cs not in SEVERITIES:
            return jsonify({"success": False, "error": "Invalid severity"}), 400
        sets.append("confirmed_severity = %s"); params.append(cs)
    if data.get("claim"):
        sets.append("assigned_to = %s"); params.append(u["username"])
    if not sets:
        return jsonify({"success": False, "error": "Nothing to update"}), 400
    sets.append("updated_at = NOW()")
    _exec(f"UPDATE bugsight_reports SET {', '.join(sets)} WHERE id = %s", (*params, rid))
    updated = _get_report(rid, u) or {}
    updated.pop("recommendations", None)
    return jsonify({"success": True, "report": updated})


@bp.get("/api/bugsight/stats")
@require_role(*ALL_ROLES)
def api_stats():
    u = _user()
    where, params = _visible_where(u)
    rows = _fetch(f"SELECT predicted_severity, confirmed_severity, component, status, confidence, created_at "
                  f"FROM bugsight_reports {where} ORDER BY id DESC LIMIT 5000", params)
    sev = {s: 0 for s in SEVERITIES}
    comp: dict[str, int] = {}
    stat: dict[str, int] = {}
    conf, trend = [], {}
    agree = judged = 0
    for r in rows:
        s = r["confirmed_severity"] or r["predicted_severity"]
        sev[s] = sev.get(s, 0) + 1
        comp[r["component"]] = comp.get(r["component"], 0) + 1
        stat[r["status"]] = stat.get(r["status"], 0) + 1
        conf.append(float(r["confidence"] or 0))
        d = str(r["created_at"] or "")[:10]
        trend[d] = trend.get(d, 0) + 1
        if r["confirmed_severity"]:
            judged += 1
            agree += r["confirmed_severity"] == r["predicted_severity"]
    today = date.today()
    days = [(today - timedelta(days=i)).isoformat() for i in range(13, -1, -1)]
    open_n = sum(v for k, v in stat.items() if k in ("Open", "In Progress"))
    return jsonify({"success": True, "total": len(rows), "open": open_n, "severity": sev,
                    "critical_open": sum(1 for r in rows if (r["confirmed_severity"] or r["predicted_severity"]) == "Critical"
                                         and r["status"] in ("Open", "In Progress")),
                    "components": dict(sorted(comp.items(), key=lambda kv: -kv[1])), "status": stat,
                    "avg_confidence": round(sum(conf) / len(conf), 3) if conf else 0,
                    "trend": [{"day": d, "count": trend.get(d, 0)} for d in days],
                    "model_agreement": {"judged": judged, "agree": int(agree)}})


@bp.get("/api/bugsight/model")
@require_role(*ALL_ROLES)
def api_model():
    rf = _state["rf"]
    info = rf.info()
    imps = sorted(zip(FEATURES, rf.model.feature_importances_), key=lambda t: -t[1])
    from .rf_model import FEATURE_LABELS
    info["importances"] = [{"feature": f, "label": FEATURE_LABELS[f], "importance": round(float(i), 4)} for f, i in imps]
    info["claude"] = {"live": _state["claude"].available, "model": _state["claude"].model}
    return jsonify({"success": True, "model": info})


@bp.post("/api/bugsight/retrain")
@require_role(*DEV_ROLES)
def api_retrain():
    rows = _fetch("SELECT * FROM bugsight_reports WHERE confirmed_severity IS NOT NULL")
    real = []
    for r in rows:
        clean, _ = normalize_input(r)
        real.append((encode(clean), SEVERITIES.index(r["confirmed_severity"])))
    meta = _state["rf"].train(real or None)
    return jsonify({"success": True, "model": meta})


@bp.post("/api/bugsight/brief")
@require_role(*DEV_ROLES)
def api_brief():
    rows = _fetch("SELECT id, title, component, predicted_severity, confirmed_severity, confidence, status "
                  "FROM bugsight_reports WHERE status IN ('Open','In Progress') ORDER BY id DESC LIMIT 100")
    items = [{"id": r["id"], "title": r["title"], "component": r["component"],
              "severity": r["confirmed_severity"] or r["predicted_severity"],
              "confidence": float(r["confidence"] or 0), "status": r["status"]} for r in rows]
    if not items:
        return jsonify({"success": True, "brief": None})
    return jsonify({"success": True, "brief": _state["claude"].triage_brief(items)})


# ---------------------------------------------------------------- bulk CSV
_TEMPLATE_COLS = ["title", "description", *FEATURES]


@bp.get("/api/bugsight/template.csv")
@require_role(*ALL_ROLES)
def api_template():
    sample = ["Payment gateway timeout", "Checkout calls time out after 30s", "network", "Payment", "production",
              8500, 45, "immediate", "no", ">50%", 32, 1]
    buf = io.StringIO()
    buf.write(",".join(_TEMPLATE_COLS) + "\n" + ",".join(f'"{c}"' for c in sample) + "\n")
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=bugsight_template.csv"})


@bp.post("/api/bugsight/batch")
@require_role(*ALL_ROLES)
def api_batch():
    import pandas as pd
    u = _user()
    f = request.files.get("file")
    if not f:
        return jsonify({"success": False, "error": "Upload a CSV file"}), 400
    try:
        df = pd.read_csv(f, nrows=MAX_BULK_ROWS + 1, dtype=str).fillna("")
    except Exception as exc:
        return jsonify({"success": False, "error": f"Could not read CSV: {exc}"}), 400
    if "title" not in {c.strip().lower() for c in df.columns}:
        return jsonify({"success": False, "error": "CSV needs a 'title' column (see the template)"}), 400
    truncated = len(df) > MAX_BULK_ROWS
    df = df.head(MAX_BULK_ROWS)
    df.columns = [c.strip().lower() for c in df.columns]
    results, skipped = [], 0
    for _, row in df.iterrows():
        title = str(row.get("title", "")).strip()
        if not title:
            skipped += 1
            continue
        pred = _state["rf"].predict(row.to_dict())
        rid = _save(pred["features"], title, str(row.get("description", ""))[:5000], pred, u, "bulk")
        results.append({"id": rid, "title": title, "component": pred["features"]["component"],
                        "severity": pred["severity"], "confidence": pred["confidence"],
                        "risk_score": pred["risk_score"], "warnings": pred["warnings"]})
    summary = {s: sum(1 for r in results if r["severity"] == s) for s in SEVERITIES}
    return jsonify({"success": True, "count": len(results), "skipped": skipped, "truncated": truncated,
                    "summary": summary, "results": results})


# ---------------------------------------------------------------- init
def init_bugsight(app, get_db, get_advisor=None, model_dir: str | None = None) -> None:
    """Register the BugSight blueprint. Call once from app.py after get_db is defined."""
    model_dir = model_dir or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models")
    _state.update(get_db=get_db, get_advisor=get_advisor, claude=BugSightClaude(),
                  rf=SeverityRF(os.path.join(model_dir, "bugsight_rf.joblib")))
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(DDL)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as exc:   # DB may be down at import time; schema.sql also creates the table
        print(f"BugSight: could not auto-create table ({exc}); run schema.sql")
    try:
        _state["rf"].ensure_ready()
        print("✅ BugSight Random Forest ready:", _state["rf"].meta.get("label_source"))
    except Exception as exc:
        print(f"❌ BugSight Random Forest failed to load: {exc}")
    app.register_blueprint(bp)
