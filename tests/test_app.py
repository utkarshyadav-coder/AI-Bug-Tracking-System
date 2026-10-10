"""End-to-end route tests using an in-memory SQLite shim instead of MySQL.
Run:  python tests/test_app.py
"""
import os, re, sqlite3, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.chdir(os.path.dirname(os.path.dirname(__file__)))
import types
if "mysql.connector" not in sys.modules:   # not needed: DB is shimmed with sqlite below
    try:
        import mysql.connector  # noqa
    except ImportError:
        m = types.ModuleType("mysql"); c = types.ModuleType("mysql.connector")
        m.connector = c; sys.modules["mysql"] = m; sys.modules["mysql.connector"] = c
import pandas as pd
from werkzeug.security import generate_password_hash

# ---- sqlite shim that quacks like mysql.connector ----
class Cur:
    def __init__(self, conn, dictionary=False):
        self.c = conn.cursor(); self.dictionary = dictionary
    def execute(self, sql, params=()):
        sql = sql.replace("%s", "?").replace("CURDATE()", "date('now')").replace("NOW()", "datetime('now')")
        sql = sql.replace("INSERT IGNORE", "INSERT OR IGNORE")
        sql = re.sub(r"DATEDIFF\(([^,]+),\s*([^)]+)\)", r"CAST(julianday(\1)-julianday(\2) AS INTEGER)", sql)
        self.c.execute(sql, tuple(params or ())); return self
    def _row(self, r):
        if r is None or not self.dictionary: return r
        return {d[0]: r[i] for i, d in enumerate(self.c.description)}
    def fetchone(self): return self._row(self.c.fetchone())
    def fetchall(self): return [self._row(r) for r in self.c.fetchall()]
    @property
    def rowcount(self): return self.c.rowcount
    def close(self): pass
class Conn:
    def __init__(self, db): self.db = db
    def cursor(self, dictionary=False): return Cur(self.db, dictionary)
    def commit(self): self.db.commit()
    def close(self): pass

db = sqlite3.connect(":memory:", check_same_thread=False)
db.executescript("""
CREATE TABLE users(username TEXT PRIMARY KEY,password TEXT,full_name TEXT,email TEXT,role TEXT,created_at TEXT);
CREATE TABLE bugs(bug_id TEXT PRIMARY KEY,title TEXT,description TEXT,severity TEXT,priority TEXT,component TEXT,
 assigned_to TEXT,reporter TEXT,reported_by TEXT,created_date TEXT,closed_date TEXT,status TEXT,resolution_time REAL,
 reopen_count INTEGER DEFAULT 0,resolution_notes TEXT,duplicate_of TEXT,ai_confidence REAL);
""")
for u, pw, role in [("dev_alice","pw","developer"),("dev_bob","pw","developer"),("dev_charlie","pw","developer"),("dev_diana","pw","developer"),("dev_evan","pw","developer"),("man","pw","manager"),("qa","pw","tester")]:
    # first dev is stored as LEGACY plaintext to test the transparent upgrade
    stored = pw if u == "dev_alice" else generate_password_hash(pw)
    db.execute("INSERT INTO users VALUES (?,?,?,?,?,?)", (u, stored, u, u+"@x", role, "2024-01-01"))
from seed_data import parse_date
df = pd.read_csv("bug_reports_FINAL_v7.csv")
df["created_date"] = parse_date(df.created_date).dt.strftime("%Y-%m-%d")
df["closed_date"] = parse_date(df.closed_date).dt.strftime("%Y-%m-%d")
df = df.where(df.notna(), None)
for _, r in df.iterrows():
    db.execute("INSERT INTO bugs(bug_id,title,description,severity,priority,component,assigned_to,reporter,reported_by,created_date,closed_date,status,resolution_time,reopen_count,resolution_notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (r.bug_id,r.title,r.description,r.severity,r.priority,r.component,r.assigned_to,r.reporter,r.reported_by,r.created_date,r.closed_date,r.status,r.resolution_time,r.reopen_count,
         f"Patched {r.component} handler and added regression test" if r.status=="Closed" else None))
db.commit()

import app as A
A.get_db = lambda: Conn(db)
A.app.config["TESTING"] = True
cl = A.app.test_client()

def login(u):
    cl.get("/logout"); r = cl.post("/login", data={"username": u, "password": "pw"}); return r

ok = fail = 0
def check(name, cond):
    global ok, fail
    cond = bool(cond)
    print(("PASS " if cond else "FAIL ") + name); ok += cond; fail += (not cond)

r = login("dev_alice"); check("legacy plaintext login works", r.status_code == 302 and "developer-dashboard" in r.location)
check("legacy password upgraded to hash", db.execute("select password from users where username='dev_alice'").fetchone()[0].startswith(("scrypt:","pbkdf2:")))
check("wrong password rejected", cl.post("/login", data={"username":"man","password":"nope"}).status_code == 200)
check("severity fallback active (no DistilBERT weights)", A.severity_model is None)

login("qa")
r = cl.post("/api/ai-advice", json={"title":"Database failed detected","description":"Database module shows failed","component":"Database"}).get_json()
check("ai-advice returns similar bugs + fixes + ETA", r["success"] and r["similar_bugs"] and r["suggested_fixes"] and r["eta"])
check("ai-advice flags near-identical open bug as duplicate", len(r["duplicates"]) >= 1)
p = cl.post("/predict-api", json={"title":"Authentication crash detected","description":"Authentication module crashes","component":"Authentication"}).get_json()
check("predict-api returns severity & priority", p["severity"] in {"Critical","High","Medium","Low"} and p["priority"].startswith("P"))

r = cl.post("/report-bug", data={"title":"Payment problem detected","description":"Payment module shows problem during normal usage","component":"Payment","auto_assign":"on"})
check("report-bug renders", r.status_code == 200 and b"AI auto-assigned" in r.data)
new = db.execute("select bug_id, assigned_to from bugs order by rowid desc limit 1").fetchone()
check("new bug auto-assigned to a developer", new[1] in ("dev_alice","dev_bob","dev_charlie","dev_diana","dev_evan"))
bid = new[0]

check("bug detail page renders", cl.get(f"/bug/{bid}").status_code == 200)
check("unknown bug -> 404", cl.get("/bug/NOPE").status_code == 404)

r = cl.post(f"/api/bug/{bid}/resolve", json={"resolution_notes": "x"}); check("tester cannot resolve", r.status_code == 403)
check("LLM plan disabled without key -> 503", cl.post(f"/api/bug/{bid}/fix-plan").status_code == 503)

# assigned developer resolves with notes; KB then learns it
dev = new[1]; db.execute("update users set password=? where username=?", (generate_password_hash("pw"), dev)); db.commit()
login(dev)
r = cl.post(f"/api/bug/{bid}/resolve", json={"resolution_notes": "short"}); check("short notes rejected", r.status_code == 400)
r = cl.post(f"/api/bug/{bid}/resolve", json={"resolution_notes": "Rotated the expired payment gateway token and added a health check"})
check("developer resolves own bug", r.get_json()["success"])
A.invalidate_ai_cache()
adv = cl.post("/api/ai-advice", json={"title":"Payment problem detected","description":"payment gateway token","component":"Payment"}).get_json()
check("new resolution notes appear in future suggestions", any("gateway token" in f["fix"] for f in adv["suggested_fixes"]))

login("man")
r = cl.get("/bugs?severity=Critical").data
check("bugs list honours severity filter", b"BUG-" in r and b'>High</span>' not in r)
db.execute("insert into bugs(bug_id,title,description,severity,priority,component,status) values('BUG-9999','UI vulnerability detected','UI module shows vulnerability','High','P1','UI','Open')"); db.commit()
r = cl.post("/api/bug/BUG-9999/auto-assign").get_json(); check("manager auto-assign works", r["success"] and r["assigned_to"])
r = cl.post("/api/bug/BUG-9999/auto-assign").get_json(); check("auto-assign refuses already-assigned bug", not r["success"])
r = cl.post(f"/api/bug/{bid}/mark-duplicate", json={"duplicate_of": "BUG-0001"}); check("mark duplicate", r.get_json()["success"])
r = cl.post(f"/api/bug/{bid}/mark-duplicate", json={"duplicate_of": "NOPE"}); check("mark duplicate validates original", r.status_code == 404)
print(f"\n{ok} passed, {fail} failed"); sys.exit(1 if fail else 0)
