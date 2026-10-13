"""
tracker_api.py
--------------
Flask blueprint that implements the REST API used by the AI-Bug-Tracker
Next.js frontend (zdawan/AI-Bug-Tracker), so the exact same UI can run on top
of your Flask + MySQL project.

Endpoints (same URLs / JSON shapes the frontend already calls):
    POST   /api/bugs                      create bug (multipart, optional screenshot)
    PATCH  /api/bugs/<id>/resolve         mark Closed (+ optional email to reporters)
    PATCH  /api/bugs/<id>/severity        change severity
    POST   /api/developers                create developer
    GET    /api/developers/email/<email>  "login" by email
    GET    /api/developers/<id>/bugs      bugs for the developer's assigned sites
    POST   /api/ai/analyze                scan a URL and suggest bugs (needs GROQ_API_KEY)
    GET    /uploads/<file>                uploaded screenshots

It uses its own tables (tracker_bugs, tracker_developers) so it cannot clash
with your existing `bugs` / `users` tables. Tables are created automatically.

Already wired into app.py via init_tracker(app).
"""
import base64
import json
import os
import re
import smtplib
import time
from email.message import EmailMessage
from urllib.parse import urlparse

import mysql.connector
from flask import Blueprint, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename

import config

try:  # only needed for the optional AI features (Hugging Face / Groq / page fetch)
    import requests
except ImportError:  # pragma: no cover
    requests = None

tracker_api = Blueprint("tracker_api", __name__)

UPLOAD_DIR = os.environ.get(
    "TRACKER_UPLOAD_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads"),
)
os.makedirs(UPLOAD_DIR, exist_ok=True)

SEVERITIES = ("Low", "Medium", "High", "Critical")
CATEGORY_LABELS = [
    "UI Bug",
    "Backend Bug",
    "Performance Bug",
    "Security Bug",
    "Database Bug",
    "Internet Error",
    "Developer Error",
    "General Bug",
]

# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------
SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS tracker_developers (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(255),
        email VARCHAR(255) NOT NULL UNIQUE,
        assigned_urls TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) CHARACTER SET utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS tracker_bugs (
        id INT AUTO_INCREMENT PRIMARY KEY,
        test_url VARCHAR(1024),
        category VARCHAR(64) NOT NULL DEFAULT 'General Bug',
        title VARCHAR(255) NOT NULL,
        description TEXT NOT NULL,
        summary TEXT,
        tags TEXT,
        severity VARCHAR(16) NOT NULL DEFAULT 'Medium',
        status VARCHAR(16) NOT NULL DEFAULT 'Open',
        reports INT NOT NULL DEFAULT 1,
        reporters TEXT,
        screenshot VARCHAR(255),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_tracker_bugs_url (test_url(191))
    ) CHARACTER SET utf8mb4
    """,
]


def get_db():
    """New MySQL connection using the project's own config.DB_CONFIG."""
    conn = mysql.connector.connect(charset="utf8mb4", **config.DB_CONFIG)
    conn.autocommit = True
    return conn


def ensure_tables():
    conn = get_db()
    try:
        cur = conn.cursor()
        for stmt in SCHEMA:
            cur.execute(stmt)
        cur.close()
    finally:
        conn.close()


def query(sql, params=(), one=False):
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        return (rows[0] if rows else None) if one else rows
    finally:
        conn.close()


def execute(sql, params=()):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        last = cur.lastrowid
        cur.close()
        return last
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Serialisers: produce the exact field names the frontend reads
# (_id, testUrl, createdAt, assignedUrls ...)
# --------------------------------------------------------------------------
def _loads(value, default):
    try:
        return json.loads(value) if value else default
    except (TypeError, ValueError):
        return default


def bug_json(r):
    return {
        "_id": str(r["id"]),
        "testUrl": r["test_url"],
        "category": r["category"],
        "title": r["title"],
        "description": r["description"],
        "summary": r["summary"],
        "tags": _loads(r["tags"], []),
        "severity": r["severity"],
        "status": r["status"],
        "reports": r["reports"],
        "reporters": _loads(r["reporters"], []),
        "screenshot": r["screenshot"],
        "createdAt": r["created_at"].isoformat() if r["created_at"] else None,
        "updatedAt": r["updated_at"].isoformat() if r["updated_at"] else None,
    }


def developer_json(r):
    return {
        "_id": str(r["id"]),
        "name": r["name"],
        "email": r["email"],
        "assignedUrls": _loads(r["assigned_urls"], []),
    }


def origin_of(url):
    try:
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}" if p.scheme and p.netloc else url
    except Exception:
        return url


# --------------------------------------------------------------------------
# AI helpers (Hugging Face when HF_API_KEY is set, keyword fallback otherwise)
# --------------------------------------------------------------------------
HF_API_KEY = os.environ.get("HF_API_KEY")

KEYWORDS = [
    ("Security Bug", ["security", "xss", "csrf", "injection", "vulnerab", "password leak", "unauthor", "token"]),
    ("Database Bug", ["database", "sql", "query", "db ", "duplicate entry", "record not saved"]),
    ("Performance Bug", ["slow", "lag", "performance", "timeout", "freez", "memory", "takes too long", "loading"]),
    ("Internet Error", ["internet", "network", "offline", "dns", "connection lost"]),
    ("Backend Bug", ["api", "server", "500", "backend", "endpoint", "request fail"]),
    ("UI Bug", ["button", "ui", "layout", "align", "css", "font", "color", "overlap", "responsive",
                "click", "link", "image", "menu", "page", "display", "text", "icon", "form"]),
]


def _hf(model, payload):
    """Call Hugging Face inference. Never raises; returns None on any failure."""
    if not HF_API_KEY or requests is None:
        return None
    try:
        res = requests.post(
            f"https://router.huggingface.co/hf-inference/models/{model}",
            headers={"Authorization": f"Bearer {HF_API_KEY}"},
            json=payload,
            timeout=15,
        )
        if not res.ok:
            return None
        return res.json()
    except Exception:
        return None


def summarize_bug(description):
    data = _hf("facebook/bart-large-cnn", {"inputs": description, "parameters": {"max_length": 60, "min_length": 10}})
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0].get("summary_text") or description
    return description


def _keyword_category(text):
    t = text.lower()
    for label, words in KEYWORDS:
        if any(w in t for w in words):
            return label
    return "General Bug"


def _zero_shot(text):
    data = _hf(
        "typeform/distilbert-base-uncased-mnli",
        {"inputs": text, "parameters": {"candidate_labels": CATEGORY_LABELS}},
    )
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return sorted(data, key=lambda d: d.get("score", 0), reverse=True)
    return None


def generate_category(text):
    ranked = _zero_shot(text)
    if ranked:
        return ranked[0].get("label") or "General Bug"
    return _keyword_category(text)


def generate_tags(text):
    ranked = _zero_shot(text)
    if ranked:
        return [d["label"] for d in ranked[:3] if "label" in d]
    return [_keyword_category(text)]


def predict_severity(description, reports=0):
    severity = "Medium"
    data = _hf(
        "facebook/bart-large-mnli",
        {
            "inputs": f"Classify this bug as Low, Medium, or High severity: {description}",
            "parameters": {"candidate_labels": ["Low", "Medium", "High"]},
        },
    )
    if isinstance(data, dict) and data.get("labels"):
        severity = data["labels"][0]

    d = description.lower()
    if any(k in d for k in ("crash", "security", "data loss")):
        severity = "High"
    elif any(k in d for k in ("slow", "performance")):
        severity = "Medium"
    elif any(k in d for k in ("typo", "alignment", "ui")):
        severity = "Low"

    if reports >= 10:
        severity = "High"
    if reports < 3 and severity == "High":
        severity = "Medium"
    return severity


def send_email(to_list, subject, text):
    user, password = os.environ.get("EMAIL_USER"), os.environ.get("EMAIL_PASS")
    if not (user and password and to_list):
        return False
    try:
        msg = EmailMessage()
        msg["From"] = f"Bug Tracker <{user}>"
        msg["To"] = ", ".join(to_list)
        msg["Subject"] = subject
        msg.set_content(text)
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as s:
            s.login(user, password)
            s.send_message(msg)
        return True
    except Exception as e:  # never break the API because of mail
        print("Email sending failed:", e)
        return False


# --------------------------------------------------------------------------
# Bugs
# --------------------------------------------------------------------------
@tracker_api.post("/api/bugs")
def create_bug():
    title = (request.form.get("title") or "").strip()
    description = (request.form.get("description") or "").strip()
    reporter = (request.form.get("reporterEmail") or "").strip()
    test_url = (request.form.get("testUrl") or "").strip() or None
    if not title or not description:
        return jsonify({"error": "title and description are required"}), 400

    screenshot_path = None
    file = request.files.get("screenshot")
    if file and file.filename:
        ext = os.path.splitext(secure_filename(file.filename))[1]
        name = f"{int(time.time() * 1000)}{ext}"
        file.save(os.path.join(UPLOAD_DIR, name))
        screenshot_path = f"/uploads/{name}"

    try:
        summary = summarize_bug(description)
        tags = generate_tags(description)
        severity = predict_severity(description)
        category = generate_category(f"{title}. {description}")

        # Same URL + same category + same title => duplicate: bump report count
        dup = query(
            "SELECT * FROM tracker_bugs WHERE test_url <=> %s AND category=%s AND title=%s LIMIT 1",
            (test_url, category, title),
            one=True,
        )
        if dup:
            if dup["status"] == "Closed":
                return jsonify({
                    "message": "This bug has already been resolved. Please verify the fix before reporting again.",
                    "resolvedInfo": {
                        "id": str(dup["id"]),
                        "title": dup["title"],
                        "resolvedAt": dup["updated_at"].isoformat() if dup["updated_at"] else None,
                        "severity": dup["severity"],
                    },
                }), 400

            reports = dup["reports"] + 1
            reporters = _loads(dup["reporters"], [])
            if reporter and reporter not in reporters:
                reporters.append(reporter)
            sev = dup["severity"]
            if reports >= 5 and sev == "Low":
                sev = "Medium"
            if reports >= 10 and sev != "High":
                sev = "High"
            execute(
                "UPDATE tracker_bugs SET reports=%s, reporters=%s, severity=%s, screenshot=COALESCE(%s, screenshot) WHERE id=%s",
                (reports, json.dumps(reporters), sev, screenshot_path, dup["id"]),
            )
            row = query("SELECT * FROM tracker_bugs WHERE id=%s", (dup["id"],), one=True)
            return jsonify({
                "message": "Duplicate bug for same URL + category. Updated report count.",
                "bug": bug_json(row),
            }), 200

        new_id = execute(
            """INSERT INTO tracker_bugs
               (test_url, category, title, description, summary, tags, severity, status, reports, reporters, screenshot)
               VALUES (%s,%s,%s,%s,%s,%s,%s,'Open',1,%s,%s)""",
            (test_url, category, title, description, summary, json.dumps(tags), severity,
             json.dumps([reporter] if reporter else []), screenshot_path),
        )
        row = query("SELECT * FROM tracker_bugs WHERE id=%s", (new_id,), one=True)
        return jsonify(bug_json(row)), 201
    except Exception as e:
        print("Error creating bug:", e)
        return jsonify({"error": str(e)}), 500


@tracker_api.patch("/api/bugs/<int:bug_id>/resolve")
def resolve_bug(bug_id):
    row = query("SELECT * FROM tracker_bugs WHERE id=%s", (bug_id,), one=True)
    if not row:
        return jsonify({"error": "Bug not found"}), 404
    execute("UPDATE tracker_bugs SET status='Closed' WHERE id=%s", (bug_id,))

    body = request.get_json(silent=True) or {}
    reporters = _loads(row["reporters"], [])
    if body.get("sendMail") and reporters:
        send_email(
            reporters,
            f"Bug Resolved: {row['title']}",
            f"Hello Tester,\n\nThe bug you reported has been marked as resolved:\n\n"
            f"Title: {row['title']}\nURL: {row['test_url'] or 'N/A'}\nSeverity: {row['severity']}\n\n"
            f"Description:\n{row['description']}\n\nThank you for helping improve the system!\n\n- Bug Tracker AI System\n",
        )
    row = query("SELECT * FROM tracker_bugs WHERE id=%s", (bug_id,), one=True)
    return jsonify({"message": "Bug marked as resolved", "bug": bug_json(row)})


@tracker_api.patch("/api/bugs/<int:bug_id>/severity")
def update_severity(bug_id):
    sev = (request.get_json(silent=True) or {}).get("severity")
    if sev not in SEVERITIES:
        return jsonify({"error": f"severity must be one of {', '.join(SEVERITIES)}"}), 400
    if not query("SELECT id FROM tracker_bugs WHERE id=%s", (bug_id,), one=True):
        return jsonify({"error": "Bug not found"}), 404
    execute("UPDATE tracker_bugs SET severity=%s WHERE id=%s", (sev, bug_id))
    return jsonify({"severity": sev})


# --------------------------------------------------------------------------
# Developers
# --------------------------------------------------------------------------
@tracker_api.post("/api/developers")
def create_developer():
    b = request.get_json(silent=True) or {}
    email = (b.get("email") or "").strip()
    if not email:
        return jsonify({"error": "email is required"}), 400
    if query("SELECT id FROM tracker_developers WHERE email=%s", (email,), one=True):
        return jsonify({"error": "A developer with this email already exists"}), 400
    new_id = execute(
        "INSERT INTO tracker_developers (name, email, assigned_urls) VALUES (%s,%s,%s)",
        (b.get("name"), email, json.dumps(b.get("assignedUrls") or [])),
    )
    row = query("SELECT * FROM tracker_developers WHERE id=%s", (new_id,), one=True)
    return jsonify(developer_json(row)), 201


@tracker_api.get("/api/developers/email/<email>")
def developer_by_email(email):
    row = query("SELECT * FROM tracker_developers WHERE email=%s", (email,), one=True)
    if not row:
        return jsonify({"error": "Developer not found"}), 404
    return jsonify(developer_json(row))


@tracker_api.get("/api/developers/<int:dev_id>/bugs")
def bugs_for_developer(dev_id):
    dev = query("SELECT * FROM tracker_developers WHERE id=%s", (dev_id,), one=True)
    if not dev:
        return jsonify({"error": "Developer not found"}), 404
    assigned = {origin_of(u) for u in _loads(dev["assigned_urls"], [])}
    rows = query("SELECT * FROM tracker_bugs ORDER BY created_at DESC, id DESC")
    return jsonify([bug_json(r) for r in rows if r["test_url"] and origin_of(r["test_url"]) in assigned])


# --------------------------------------------------------------------------
# AI: scan a page and suggest bugs
# --------------------------------------------------------------------------
def _load_page(url):
    """Return (visible_text, screenshot_base64_or_None). Uses Playwright if
    installed (gives a screenshot), else plain requests + BeautifulSoup."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                text = page.inner_text("body")
                shot = page.screenshot(type="png")
            finally:
                browser.close()
        return text, base64.b64encode(shot).decode()
    except Exception as e:
        print("Playwright unavailable, using plain HTTP fetch:", e)

    res = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0 BugTracker"})
    res.raise_for_status()
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(res.text, "html.parser")
        for t in soup(["script", "style", "noscript"]):
            t.decompose()
        text = soup.get_text("\n", strip=True)
    except ImportError:
        text = re.sub(r"<[^>]+>", " ", res.text)
    return text, None


def _extract_json(raw):
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    try:
        return json.loads(raw)
    except ValueError:
        m = re.search(r"\{.*\}", raw, re.S)
        return json.loads(m.group(0)) if m else None


@tracker_api.post("/api/ai/analyze")
def analyze():
    website_url = ((request.get_json(silent=True) or {}).get("websiteUrl") or "").strip()
    if not website_url:
        return jsonify({"error": "websiteUrl is required"}), 400
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key or requests is None:
        return jsonify({"error": "GROQ_API_KEY is not set on the server (or 'requests' is not installed)"}), 503

    url = website_url if website_url.startswith(("http://", "https://")) else f"https://{website_url}"
    try:
        page_text, screenshot_b64 = _load_page(url)

        existing = query("SELECT title, description FROM tracker_bugs WHERE test_url=%s", (website_url,))
        titles = "\n".join(b["title"] for b in existing)
        descs = "\n".join(b["description"] for b in existing)

        prompt = f"""
You are an expert UI inspector.

Extract up to 5 NEW and DIFFERENT UI or functionality bugs from the webpage text.

VERY IMPORTANT - DO NOT REPEAT BUGS:
Below are bugs ALREADY reported for this page. Do NOT return anything similar.

Already Reported Bug Titles:
{titles}

Already Reported Bug Descriptions:
{descs}

Your task:
- Return ONLY NEW bugs not similar to the above.
- Each bug must contain:
  "title": short UI element name (EXACT element)
  "description": a clear explanation of a NEW issue

Return STRICT JSON ONLY:

{{
  "bugs": [
    {{ "title": "element name", "description": "issue details" }}
  ]
}}

Website Content:
{page_text[:12000]}
"""
        ai = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "llama-3.1-8b-instant", "messages": [{"role": "user", "content": prompt}]},
            timeout=60,
        )
        ai.raise_for_status()
        raw = ai.json()["choices"][0]["message"]["content"]
        parsed = _extract_json(raw)
        if not parsed:
            return jsonify({"error": "AI returned invalid JSON", "raw": raw}), 500

        processed = []
        for bug in parsed.get("bugs", []):
            category = generate_category(bug.get("description", ""))
            exists = query(
                "SELECT id FROM tracker_bugs WHERE test_url=%s AND title=%s AND category=%s LIMIT 1",
                (website_url, bug.get("title"), category),
                one=True,
            )
            processed.append({
                "title": bug.get("title"),
                "description": bug.get("description"),
                "category": category,
                "duplicate": bool(exists),
            })

        if all(b["duplicate"] for b in processed):
            return jsonify({
                "duplicate": True,
                "message": "No NEW bugs found. All detected bugs are already reported.",
                "bugs": processed,
                "screenshotBase64": screenshot_b64,
            })
        return jsonify({"duplicate": False, "bugs": processed, "screenshotBase64": screenshot_b64})
    except Exception as e:
        print("AI ANALYZE ERROR:", e)
        return jsonify({"error": "AI analysis failed", "details": str(e)}), 500


# --------------------------------------------------------------------------
# Uploaded screenshots + setup helper
# --------------------------------------------------------------------------
@tracker_api.get("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


def init_tracker(app):
    """Call once from app.py: enables CORS for the frontend, registers the
    blueprint and creates the tracker tables."""
    origins = [
        o.strip()
        for o in os.environ.get(
            "TRACKER_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
        ).split(",")
        if o.strip()
    ]
    try:
        from flask_cors import CORS

        CORS(tracker_api, origins=origins)
    except ImportError:
        print("WARNING: flask-cors is not installed (pip install flask-cors); the frontend will be blocked by CORS.")

    app.register_blueprint(tracker_api)
    try:
        ensure_tables()
    except Exception as e:
        print("WARNING: could not create tracker tables (check DB_* env vars):", e)
