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
