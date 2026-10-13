# Deployment guide

DataPulse AI runs fully on a local machine; nothing here is required for development or assessment. This guide explains how to host it online when you choose to. It has **not** been deployed by the author of this guide to any specific account, and hosting dashboards change their menus over time, so treat the platform-specific steps as a map and check each provider's current documentation.

## Target architecture

```mermaid
flowchart LR
    U[Browser] -- HTTPS --> FE[Streamlit host<br/>frontend/app.py]
    FE -- HTTPS + Bearer token --> BE[Python web-service host<br/>FastAPI backend]
    BE -- TLS --> DB[(Managed PostgreSQL)]
    BE --> DISK[(Persistent disk<br/>data/)]
    BE -. HTTPS .-> LLM[(LLM provider)]
```

| Component | Requirement | Example options |
|---|---|---|
| Frontend | Runs `streamlit run`; can set environment variables or secrets | Streamlit Community Cloud, Hugging Face Spaces (Streamlit), Render, Railway |
| Backend | Persistent Python web service, HTTPS, environment variables, ideally a persistent disk | Render, Railway, Fly.io, Koyeb, a small VM |
| Database | PostgreSQL 14+ with TLS | Neon, Supabase, Render PostgreSQL, Railway PostgreSQL, Aiven |
| LLM (optional) | HTTPS API reachable from the backend | Any OpenAI-compatible provider or Anthropic |

## 1. Push the project to GitHub

```bash
git init
git add .
git status            # confirm .env and data/ files are NOT listed
git commit -m "DataPulse AI"
git branch -M main
git remote add origin https://github.com/<you>/datapulse-ai.git
git push -u origin main
```

`.gitignore` excludes `.env`, `data/` contents and the development encryption key. Never commit real credentials; if you ever do, rotate them immediately, because removing the commit does not remove the secret from history.

GitHub Actions (`.github/workflows/ci.yml`) runs the tests on every push. Check the **Actions** tab is green before deploying.

## 2. Create the database

Create a PostgreSQL database with your provider and copy its connection string. Convert it to SQLAlchemy form and require TLS:

```
postgresql+psycopg2://USER:PASSWORD@HOST:5432/DBNAME?sslmode=require
```

Restrict access where the provider allows it (IP allow-list or private networking to the backend only). The schema is created automatically by Alembic when the backend starts (`AUTO_MIGRATE=true`).

## 3. Deploy the backend

Generate production secrets locally:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"                                 # SECRET_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # DATA_ENCRYPTION_KEY
```

Store `DATA_ENCRYPTION_KEY` somewhere safe: files encrypted with it cannot be read without it.

### Option A: native Python service (for example Render "Web Service")

| Setting | Value |
|---|---|
| Root directory | `backend` |
| Build command | `pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt` |
| Start command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers` |
| Health check path | `/health` |

### Option B: Docker

Build the `backend` target of the root `Dockerfile` (`docker build --target backend .`). The image listens on `$PORT` (default 8000) and has a health check.

### Environment variables (backend)

| Variable | Value |
|---|---|
| `APP_ENV` | `production` (disables `/docs`, enables HSTS, requires secrets) |
| `DATABASE_URL` | the URL from step 2 |
| `SECRET_KEY` | generated value |
| `DATA_ENCRYPTION_KEY` | generated value |
| `CORS_ORIGINS` | your frontend URL, e.g. `https://datapulse-yourname.streamlit.app` |
| `BOOTSTRAP_ADMIN_USERNAME` / `BOOTSTRAP_ADMIN_PASSWORD` | your admin account (strong password); add engineer/viewer accounts the same way or later from the Administration page |
| `ENABLE_FAULT_INJECTION` | `false` unless you are giving a demonstration |
| `DATA_DIR` | path of the persistent disk mount, e.g. `/var/data` (see below) |
| `EMBEDDING_BACKEND` | `tfidf` on instances with ≤ 1 GB RAM; `auto` otherwise |
| `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` | optional, see below |

### Persistent storage

Run, incident and audit metadata live in PostgreSQL and survive restarts. Uploaded datasets, processed/quarantine files, trained models and the FAISS index live under `DATA_DIR`:

- **With a persistent disk** mounted at `DATA_DIR`, everything survives restarts and redeploys.
- **Without one** (many free tiers have an ephemeral filesystem): the FAISS index is rebuilt automatically from `knowledge_base/` on start-up and Isolation Forest models are retrained from the stored history on the next run, but uploaded files and generated outputs are lost on restart. Runs, incidents and reports remain; downloads of old processed files and re-runs of old datasets will report that the file is unavailable. This is acceptable for a demonstration, not for real use.

### Seed demonstration data (optional)

From the provider's shell (or locally with the production `DATABASE_URL`, `DATA_DIR` and `DATA_ENCRYPTION_KEY` set):

```bash
python scripts/seed_database.py
```

### Verify

```bash
curl https://<backend-host>/health
# {"status":"ok","database":true,"llm_configured":false,"version":"1.0.0"}
```

## 4. Deploy the frontend

### Streamlit Community Cloud

1. **Create app** → choose the repository and branch `main`.
2. **Main file path:** `frontend/app.py` (Streamlit installs `frontend/requirements.txt`, which contains only the dashboard's dependencies).
3. **Advanced settings → Secrets:**

   ```toml
   API_BASE_URL = "https://<backend-host>"
   ```

   Root-level secrets are exposed to the app as environment variables, which is how `api_client.py` reads the URL.
4. Deploy, then add the resulting `https://….streamlit.app` URL to the backend's `CORS_ORIGINS` and redeploy the backend.

### Any other host

Run `streamlit run app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true` from `frontend/` (or build the `frontend` Docker target) with `API_BASE_URL` set.

**Never put `LLM_API_KEY`, `DATABASE_URL` or any backend secret in the frontend's settings.** The dashboard needs only `API_BASE_URL`.

## 5. Configure the LLM (optional)

Set on the backend only:

```ini
LLM_PROVIDER=openai_compatible       # or anthropic
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=<model id from your provider>
LLM_API_KEY=<secret>
LLM_TIMEOUT_SECONDS=30
LLM_MAX_RETRIES=2
LLM_MAX_OUTPUT_TOKENS=900
```

### Managing cost and rate limits

- Calls happen only when someone presses **Analyse incident** or asks the assistant a question; pipeline runs never call the LLM.
- Each analysis sends one request with the evidence pack and up to four retrieved sections, and asks for at most `LLM_MAX_OUTPUT_TOKENS` tokens.
- 429 responses are retried with the provider's `Retry-After` (capped at 30 s) up to `LLM_MAX_RETRIES`; after that the assistant falls back to rule-based answers and says so.
- Set a monthly spending limit in the provider's console, use a key dedicated to this deployment, and prefer a small, inexpensive model; the prompts are short and structured.
- For zero-cost demonstrations, leave the key empty (rule-based mode) or point `LLM_BASE_URL` at a self-hosted OpenAI-compatible server.

## 6. Test the public deployment

1. Open the frontend URL and sign in as admin. The sidebar should show the assistant mode and retrieval backend.
2. Data ingestion → Synthetic samples → `synthetic_sales_clean.csv` → Use → Run pipeline: all five stages green.
3. Run `synthetic_sales_invalid_schema_change.csv`: the run fails at Validate and opens a critical incident.
4. AI incident analyst → Analyse incident: the source label should say LLM (if configured) or rule-based.
5. Recovery → apply column mapping → the incident resolves.
6. Reports → download a CSV; Administration → audit log shows your actions with your public IP.
7. Sign in as a viewer and confirm uploads and recovery are unavailable and customer IDs are masked.
8. Confirm `https://<backend-host>/docs` returns 404 (production mode).

## 7. Operating checklist

- Rotate `SECRET_KEY` to invalidate all tokens if one is exposed.
- Back up PostgreSQL (most managed providers do this daily) and the persistent disk.
- Schedule `python scripts/purge_old_data.py --apply` (for example weekly) to enforce `RETENTION_DAYS`.
- Review the audit log for repeated `login` failures.
- Keep dependencies updated and re-run the test suite before redeploying.
