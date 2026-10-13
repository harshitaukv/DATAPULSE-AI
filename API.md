# DataPulse AI — REST API reference

Base URL: `http://localhost:8000` (configurable). Interactive OpenAPI documentation is served at `/docs` and `/redoc` in development; both are disabled when `APP_ENV=production`.

Every endpoint except `/health` and `/api/v1/auth/login` requires `Authorization: Bearer <token>`. Roles are hierarchical: **viewer < engineer < admin**. A role column entry means "this role or higher".

## Authentication and users

| Method | Path | Purpose | Role |
|---|---|---|---|
| POST | `/api/v1/auth/login` | Exchange username and password for an access token. Five failures in five minutes lock the account temporarily (HTTP 429). | public |
| GET | `/api/v1/auth/me` | Current user, role and effective permissions. | any signed-in user |
| GET | `/api/v1/users` | List users. | admin |
| POST | `/api/v1/users` | Create a user (password strength enforced). | admin |

## Datasets and samples

| Method | Path | Purpose | Role |
|---|---|---|---|
| POST | `/api/v1/uploads` | Upload a CSV/JSON file (multipart `file`). Validates type, size, encoding and structure; stores it encrypted. Returns metadata, a masked preview and a contract check. | engineer |
| GET | `/api/v1/uploads` | List datasets (paginated: `limit`, `offset`). | viewer |
| GET | `/api/v1/uploads/{dataset_id}/preview` | First rows plus contract check. Sensitive columns are masked unless you are the uploader or an admin. | viewer |
| DELETE | `/api/v1/uploads/{dataset_id}` | Delete the stored file and mark the dataset deleted (metadata retained). | admin |
| GET | `/api/v1/samples` | List the synthetic sample datasets. | viewer |
| GET | `/api/v1/samples/{filename}` | Download a regenerated synthetic sample. | viewer |
| POST | `/api/v1/samples/{filename}/import` | Regenerate a sample and register it as a dataset. | engineer |

## Pipelines and runs

| Method | Path | Purpose | Role |
|---|---|---|---|
| GET | `/api/v1/pipelines` | List registered pipelines and their contracts. | viewer |
| POST | `/api/v1/pipelines` | Register a pipeline with a column contract. | admin |
| GET | `/api/v1/pipelines/{pipeline_id}` | Pipeline detail. | viewer |
| POST | `/api/v1/pipelines/{pipeline_id}/runs` | Run the pipeline on a dataset: `{"dataset_id": "...", "fault_injection": {...}}` (failure simulation is optional, engineer+, and can be disabled). | engineer |
| GET | `/api/v1/runs` | List runs (filters: `pipeline_id`, `status`; paginated). | viewer |
| GET | `/api/v1/runs/{run_id}` | Run detail: stage log with every attempt, metrics, anomaly verdict, report. | viewer |
| GET | `/api/v1/runs/{run_id}/quality` | Quality report: checks, schema, findings, quarantine reasons and a (masked) quarantine sample. | viewer |
| GET | `/api/v1/runs/{run_id}/download/{kind}` | `report` (JSON, any role); `processed` or `quarantine` CSV (admin, or the engineer who ran it). | viewer / engineer |

## Incidents and recovery

| Method | Path | Purpose | Role |
|---|---|---|---|
| GET | `/api/v1/incidents` | List incidents (filters: `status`, `severity`, `incident_type`, `run_id`; comma-separated values allowed). | viewer |
| GET | `/api/v1/incidents/{incident_id}` | Incident detail including evidence, policy and currently eligible recovery actions. | viewer |
| PATCH | `/api/v1/incidents/{incident_id}` | Change status and append a timestamped resolution note. | engineer |
| POST | `/api/v1/incidents/{incident_id}/analyze` | Evidence-grounded analysis (LLM when configured, labelled rule-based fallback otherwise) with retrieved documentation. | engineer |
| POST | `/api/v1/incidents/{incident_id}/recover` | Request a predefined action: `retry_run`, `rerun_with_dataset`, `apply_column_mapping`, `escalate`. Supports `idempotency_key`. | engineer |
| GET | `/api/v1/recovery-logs` | Recovery history (filters: `incident_id`, `result`, `approval_status`). | viewer |
| POST | `/api/v1/recovery-logs/{log_id}/decision` | Approve (and execute) or reject a pending request. | admin |
| GET | `/api/v1/recovery/policies` | The policy catalogue and which actions need approval. | viewer |

## Analytics, assistant and reports

| Method | Path | Purpose | Role |
|---|---|---|---|
| GET | `/api/v1/analytics/overview` | Totals, success rate, average quality, open incidents, recovery success rate. All computed from stored records. | viewer |
| GET | `/api/v1/analytics/trends` | Runs per day, per-run series, incidents by severity and type. | viewer |
| POST | `/api/v1/assistant/chat` | Ask a question, optionally about an incident: `{"question", "incident_id", "history"}`. | viewer |
| GET | `/api/v1/assistant/search` | Search the knowledge base (`q`, `k`). | viewer |
| GET | `/api/v1/assistant/status` | LLM mode and RAG index status. | viewer |
| POST | `/api/v1/assistant/rebuild-index` | Rebuild the FAISS index from the knowledge base. | admin |
| GET | `/api/v1/reports/{kind}` | `pipeline_runs`, `data_quality`, `incidents`, `recovery_audit` (viewer) or `audit_log` (admin); `format=csv|json`. | viewer / admin |

## Administration and health

| Method | Path | Purpose | Role |
|---|---|---|---|
| GET | `/api/v1/audit-logs` | Audit trail (filters: `action`, `username`). | admin |
| POST | `/api/v1/admin/retention/apply` | Apply the retention policy (`dry_run=true` by default). | admin |
| GET | `/health` | Liveness and database connectivity (HTTP 503 when the database is unreachable). | public |

## Error format

Errors return `{"detail": "<human-readable message>"}` with an appropriate status code: 400 (request not allowed by policy), 401 (not signed in), 403 (role not permitted), 404, 409 (conflict, e.g. incident already resolved or retry limit reached), 410 (dataset deleted), 413 (file too large), 422 (validation; includes an `errors` list), 429 (sign-in throttled), 503 (database unavailable). Stack traces, file paths and database details are never returned.
