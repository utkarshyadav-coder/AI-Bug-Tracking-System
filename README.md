# AI-Driven Intelligent Bug Tracking & Developer Productivity System

This is a rebuild of the reference project onto your required stack:

| Layer         | Technology                                   |
|---------------|-----------------------------------------------|
| Frontend      | HTML + CSS + vanilla JavaScript (fetch API)   |
| Backend       | Java 17 + Spring Boot 3 (REST API, JWT auth)  |
| Database      | MySQL                                         |
| AI / ML       | Python (Flask microservice, existing trained models) |
| Integration   | REST over HTTP between all three tiers        |

## Why a separate ML microservice?

Spring Boot has no native way to run your trained DistilBERT / XGBoost /
scikit-learn models — those need Python. So the ML models stay in a small
Flask service, and Spring Boot calls it over REST (`MLClient.java`) instead
of trying to re-implement or embed the models in Java. This is the standard
pattern for polyglot ML systems and keeps each piece simple:

```
 Browser (HTML/CSS/JS)
        │  fetch() + JWT
        ▼
 Spring Boot backend  ──REST──▶  Python ML microservice (Flask)
        │                              (severity / priority / dev-suggestion
        ▼                               models, already trained — copied
      MySQL                             from your original repo's /models)
```

## Folder structure

```
bug-tracker-system/
├── backend/          Spring Boot Maven project
├── ml-service/        Flask app + your existing trained models
├── frontend/           Static HTML/CSS/JS
├── database/           schema.sql + seed.sql
└── README.md
```

## 1. Database setup (MySQL)

```bash
mysql -u root -p < database/schema.sql
# edit database/seed.sql with real BCrypt password hashes, then:
mysql -u root -p < database/seed.sql
```

Tables: `users`, `bugs`, `sprints`, `sprint_bugs` — modeled on the columns
your original `app.py` was already querying.

To generate a real BCrypt hash for a password, you can temporarily add this
to any Spring Boot component and print the result, or use an online BCrypt
generator for local dev only:
```java
new BCryptPasswordEncoder().encode("yourPassword");
```

## 2. ML microservice (Python)

```bash
cd ml-service
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py                   # runs on http://localhost:5001
```

This loads the **same trained models** from your original repo
(`bug_severity_model/`, `priority_xgboost_model.pkl`,
`developer_assignment_data.pkl`, etc.) — nothing needed retraining.

Endpoints:
- `GET  /health`
- `POST /api/ml/predict` `{ title, description, component }` → `{ severity, priority }`
- `POST /api/ml/suggest-developers` `{ component, topN }` → `{ suggestions: [...] }`

## 3. Backend (Spring Boot)

Edit `backend/src/main/resources/application.properties`:
- `spring.datasource.password` → your MySQL password
- `jwt.secret` → a long random string
- `ml.service.base-url` → where the Flask service is running

Then:
```bash
cd backend
mvn spring-boot:run       # runs on http://localhost:8080
```

Key endpoints:
- `POST /api/auth/login` → returns a JWT
- `POST /api/bugs` (auth required) → reports a bug; backend calls the ML
  service for severity/priority before saving to MySQL
- `GET  /api/bugs` → list bugs (all for manager/admin, own for others)
- `POST /api/bugs/{bugId}/verify` → tester marks Verified / Reopened
- `POST /api/bugs/suggest-developers` → proxies to the ML service
- `GET  /api/dashboard/stats` → counts by severity/status

## 4. Frontend

Just open `frontend/login.html` in a browser, or serve the folder with any
static file server (e.g. `npx serve frontend`). It talks to the backend at
`http://localhost:8080/api` — change `API_BASE` in `js/api.js` if you deploy
elsewhere.

## What's implemented vs. what to extend

**Implemented end-to-end:** login (JWT), report a bug with live ML
severity/priority prediction, list bugs, dashboard stat counts, bug
verification, developer suggestion endpoint.

**From your original Flask app, still to port if your project needs them**
(the logic already exists in the extracted `app.py` for reference):
- Role-specific dashboard pages (admin/manager/tester/developer views with
  charts) — currently one shared dashboard; you can add role checks and
  extra HTML pages the same way `report-bug.html` was built.
- Sprint risk analysis (`models/sprint_risk.py` + the `/manager/sprint-risk`
  route) — add a `SprintController` in the backend and a `sprint-risk.html`
  page following the same pattern as `BugController`/`bugs.html`.
- User registration UI (currently: insert directly via `seed.sql` or add a
  `/api/auth/register` endpoint mirroring `AuthController.login`).

All the trained ML models (severity, priority, developer assignment, sprint
risk) were carried over unchanged into `ml-service/models/` — only the
serving code changed from Flask-monolith to Flask-microservice.
