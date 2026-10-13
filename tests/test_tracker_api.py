"""Tests for tracker_api.py (the API behind the Next.js portal) using an in-memory SQLite shim.
Run:  python tests/test_tracker_api.py
"""
import datetime, io, os, sqlite3, sys, types
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.chdir(os.path.dirname(os.path.dirname(__file__)))
if "mysql.connector" not in sys.modules:
    try:
        import mysql.connector  # noqa
    except ImportError:
        m = types.ModuleType("mysql"); c = types.ModuleType("mysql.connector")
        m.connector = c; sys.modules["mysql"] = m; sys.modules["mysql.connector"] = c
import tempfile
os.environ["TRACKER_UPLOAD_DIR"] = tempfile.mkdtemp()
import tracker_api as t

db = sqlite3.connect(":memory:", check_same_thread=False); db.row_factory = sqlite3.Row
db.executescript("""
CREATE TABLE tracker_developers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, email TEXT UNIQUE NOT NULL, assigned_urls TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE tracker_bugs (id INTEGER PRIMARY KEY AUTOINCREMENT, test_url TEXT, category TEXT NOT NULL DEFAULT 'General Bug', title TEXT NOT NULL, description TEXT NOT NULL, summary TEXT, tags TEXT, severity TEXT NOT NULL DEFAULT 'Medium', status TEXT NOT NULL DEFAULT 'Open', reports INT NOT NULL DEFAULT 1, reporters TEXT, screenshot TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
""")
tr = lambda sql: sql.replace("%s", "?").replace("<=>", "IS")
def fix(r):
    d = dict(r)
    for k in ("created_at", "updated_at"):
        if isinstance(d.get(k), str): d[k] = datetime.datetime.fromisoformat(d[k])
    return d
def query(sql, params=(), one=False):
    rows = [fix(r) for r in db.execute(tr(sql), params).fetchall()]
    return (rows[0] if rows else None) if one else rows
def execute(sql, params=()):
    c = db.execute(tr(sql), params); db.commit(); return c.lastrowid
t.query, t.execute = query, execute

from flask import Flask
app = Flask(__name__); app.register_blueprint(t.tracker_api); c = app.test_client()
fails = []
def ok(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: fails.append(name)

r = c.post("/api/developers", json={"name": "Dev", "email": "githubtest@gmail.com", "assignedUrls": ["https://github.com/"]}); ok("create developer", r.status_code == 201)
ok("duplicate developer -> 400", c.post("/api/developers", json={"email": "githubtest@gmail.com"}).status_code == 400)
dev = c.get("/api/developers/email/githubtest@gmail.com").get_json(); ok("login by email", dev["assignedUrls"] == ["https://github.com/"] and "_id" in dev)
ok("unknown email -> 404", c.get("/api/developers/email/nobody@x.com").status_code == 404)

form = {"title": "Login button", "description": "Login button not working on click", "reporterEmail": "a@x.com",
        "testUrl": "https://github.com/login", "screenshot": (io.BytesIO(b"\x89PNG fake"), "s.png")}
r = c.post("/api/bugs", data=form, content_type="multipart/form-data"); b = r.get_json()
ok("create bug", r.status_code == 201 and b["reports"] == 1 and b["screenshot"].startswith("/uploads/"))
form2 = {k: v for k, v in form.items() if k != "screenshot"}; form2["reporterEmail"] = "b@x.com"
r = c.post("/api/bugs", data=form2, content_type="multipart/form-data")
ok("duplicate bumps report count", r.status_code == 200 and r.get_json()["bug"]["reports"] == 2)
ok("missing fields -> 400", c.post("/api/bugs", data={"title": ""}, content_type="multipart/form-data").status_code == 400)
bugs = c.get(f"/api/developers/{dev['_id']}/bugs").get_json(); ok("developer sees bugs for assigned site", len(bugs) == 1)
bid = bugs[0]["_id"]
ok("update severity", c.patch(f"/api/bugs/{bid}/severity", json={"severity": "Critical"}).get_json() == {"severity": "Critical"})
ok("invalid severity -> 400", c.patch(f"/api/bugs/{bid}/severity", json={"severity": "x"}).status_code == 400)
ok("resolve bug", c.patch(f"/api/bugs/{bid}/resolve", json={"sendMail": False}).get_json()["bug"]["status"] == "Closed")
ok("re-report resolved bug -> 400", c.post("/api/bugs", data=form2, content_type="multipart/form-data").status_code == 400)
ok("analyze without URL -> 400", c.post("/api/ai/analyze", json={}).status_code == 400)
ok("serves uploaded screenshot", c.get(b["screenshot"]).status_code == 200)
print("\n%d failed" % len(fails) if fails else "\nall passed")
sys.exit(1 if fails else 0)
