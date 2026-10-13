# AI-Driven Bug Tracking & Resolution System

Built on your original project (Flask + MySQL + DistilBERT/XGBoost). The original
system **classified** bugs (severity, priority) and suggested developers. This version
adds the missing half: **resolving** them.

## What's new

| Capability | How it works | Where |
|---|---|---|
| **Duplicate detection** | TF-IDF cosine similarity (>= 0.82) against all bugs, shown live while reporting | `ai/resolution_engine.py`, report form |
| **Fix suggestions from history** | Mines the `resolution_notes` of similar *resolved* bugs, ranked by similarity | `/bug/<id>` page |
| **Time-to-fix estimate** | Similarity-weighted mean of similar bugs' resolution time, with range | bug page + report form |
| **Smarter auto-assignment** | Evidence from similar bugs fixed + component expertise + speed + reopen rate, penalised by *live* workload | `ResolutionAdvisor.recommend_developers` |
| **Learning loop** | Developers close bugs with fix notes (`/api/bug/<id>/resolve`); the knowledge base rebuilds so the next similar bug gets that fix suggested | resolve box on bug page |
| **LLM fix plan (optional)** | Claude drafts root-cause hypotheses, fix steps and a test plan grounded in similar bugs | needs `ANTHROPIC_API_KEY` |
| **Severity fallback** | TF-IDF + logistic regression when DistilBERT weights are missing | `FallbackSeverity` |

## Fixes to the original project

- **Hardcoded MySQL password** removed from `app.py` and `models/*.py` -> `config.py` / env vars. **Rotate that password**, it was in your repo history.
- **Plaintext passwords** -> hashed (werkzeug). Existing plaintext rows are accepted once and upgraded automatically on next login.
- **`models/bug_severity_model/` had no weights** (`model.safetensors` missing), so severity silently always returned "Medium". Now falls back to a trained classifier, and logs it.
- **Severity/priority filters** on the bugs page were sent by the form but ignored by the server.
- **CSV date formats are mixed** (`01-01-24` and `2026-03-30`); the seed script handles both.
- `debug=True` is now opt-in (`FLASK_DEBUG=1`).
- No SQL schema existed -> `schema.sql` + `seed_data.py` added.

## Setup

```bash
pip install -r requirements.txt
mysql -u root -p < schema.sql
export DB_PASSWORD='your-mysql-password' SECRET_KEY='something-long-and-random'
python seed_data.py          # demo users + 399 bugs
python app.py
```

Existing database? Add the new columns instead of re-creating tables:

```sql
ALTER TABLE bugs ADD COLUMN resolution_notes TEXT NULL,
                 ADD COLUMN duplicate_of VARCHAR(20) NULL,
                 ADD COLUMN ai_confidence FLOAT NULL;
```

Demo logins (from `seed_data.py`): `admin/admin123`, `manager1/manager123`, `dev_alice/dev123`, `qa_sarah/qa123`.

Optional LLM plans: `pip install anthropic && export ANTHROPIC_API_KEY=...`

## Tests

```bash
python tests/test_engine.py   # (or pytest) engine logic
python tests/test_app.py      # 21 route tests, MySQL replaced by an in-memory SQLite shim
```

## Known limitations (read before demoing)

- **Your dataset is synthetic.** Only 138 distinct titles, all templated ("X module shows Y during normal
  usage"), and the CSV has **no resolution notes**. Fix suggestions stay empty for old bugs until developers
  start closing bugs with notes. For a credible demo, resolve a handful of bugs with real notes first.
- **Duplicate threshold (0.82)** is tuned by eye. On templated data many bugs look like duplicates; on real
  data, tune `DUPLICATE_THRESHOLD`.
- **Sprint risk** still uses the rule-based score in `app.py`; `sprint_risk_model.pkl` is trained on
  *simulated* sprints and is not wired in. I left it alone rather than present it as real prediction.
- The DistilBERT model needs retraining (`models/severity.py`) to restore it; until then the fallback is used.
- Not tested against a real MySQL server (none available here), only the SQLite shim. `DATEDIFF`/`CURDATE`
  are standard MySQL, but run `seed_data.py` and click through once.

## Tester / Developer web portal (Next.js UI)

`frontend/` holds the Next.js + Tailwind portal copied from zdawan/AI-Bug-Tracker (same UI).
It talks to this Flask app through `tracker_api.py` (wired in `app.py` with `init_tracker(app)`),
which stores its data in two separate tables (`tracker_bugs`, `tracker_developers`) so your
existing `bugs` / `users` tables and ML pipeline are untouched.

**Run locally (two terminals)**

```
# 1) backend (from the project root)
pip install -r requirements.txt
mysql -u root -p < schema.sql              # creates DB `bugtracker` incl. the tracker_* tables
mysql -u root -p < tracker_seed.sql        # optional: developer githubtest@gmail.com for the portal
export DB_PASSWORD='your-mysql-password' SECRET_KEY='long-random-string'   # Windows PowerShell: $env:DB_PASSWORD='...'
python app.py                              # http://localhost:5000  (existing dashboards + portal API)

# 2) portal UI
cd frontend
cp .env.local.example .env.local           # NEXT_PUBLIC_API_URL=http://localhost:5000
npm install
npm run dev                                # http://localhost:3000
```

* Tester side: open http://localhost:3000 -> *Enter as Tester* -> paste the site URL -> report a bug.
* Developer side: *Enter as Developer* -> log in with `githubtest@gmail.com` (sees bugs for the URLs assigned in `tracker_developers.assigned_urls`).
* *AI Analyze* needs `GROQ_API_KEY`; `HF_API_KEY` improves category/severity (keyword fallback otherwise); `EMAIL_USER` / `EMAIL_PASS` (Gmail app password) enable "Send mail to tester". See `env.example`.
* macOS: port 5000 is often used by AirPlay; run Flask on another port (`flask run -p 5001` or edit `app.run`) and change `NEXT_PUBLIC_API_URL`.
* Extra tests: `python tests/test_tracker_api.py`

## BugSight AI module (Developer + Tester dashboard)

Open **`/bugsight`** after logging in (new "BugSight AI" item in the nav bar). One page, two modules chosen by role:

| | Tester module | Developer module |
|---|---|---|
| Analyze a bug (structured form -> Random Forest severity, confidence, class probabilities, per-tree votes, feature importance) | yes | yes |
| Claude recommendation | repro steps, missing info, verification checklist, regression areas | root causes, fix steps, where to look, test plan, ETA, prevention |
| Bulk CSV upload (<= 500 rows, `/api/bugsight/template.csv`) | yes | - |
| Reports | own reports only | **triage queue** of all reports, highest predicted severity first |
| Status / assign-to-me / **confirm actual severity** | - | yes |
| Insights (severity mix, components, 14-day trend, feature importance) + Claude triage brief | - | yes |
| Retrain the forest on confirmed severities | - | yes |

Admins/managers see the developer module and can switch with `?view=tester`.

**How it works**

- `bugsight/rf_model.py` - a real `sklearn.ensemble.RandomForestClassifier` (150 trees) over 10 structured features. Saved to `models/bugsight_rf.joblib` and trained automatically on first start.
- `bugsight/llm.py` - Claude (`ANTHROPIC_API_KEY`, model via `ANTHROPIC_MODEL`, default `claude-sonnet-5-5`). The prompt includes the forest's prediction and the most similar *resolved* bugs from your existing `ResolutionAdvisor`, so advice is grounded in your own fix history. Without a key the dashboard still works and clearly labels output as "rule-based fallback". Bug text is passed as delimited, untrusted data.
- `bugsight/routes.py` - Flask blueprint, role checks, table `bugsight_reports` (in `schema.sql`, also auto-created at startup). Claude responses are cached per report and role.
- Next.js portal (`frontend/`) is untouched; the JSON API under `/api/bugsight/*` can be called from it later.

**Important: what the forest is trained on.** Your CSV has no structured impact data (affected users, frequency, environment...), so the forest is bootstrapped on a *synthetic*, rule-labelled dataset (holdout ~64% exact, ~97% within one severity level; this measures agreement with the synthetic rules, **not** real-world accuracy). Developers should set *Confirmed severity* on real reports and press **Retrain**: confirmed rows are blended in with 8x weight, and the dashboard shows how often the model agreed with developers. Expect usefulness to depend on that feedback loop.

Tests: `python tests/test_bugsight.py` (46 checks; SQLite shim, Claude client faked).
