# DataPulse AI — mapping to the Wipro CPPE modules

This document maps the project to the four Wipro COE CPPE training modules. Each table separates what is **implemented** in the code (with the file where you can show it) from what is covered **conceptually** (explained in the report and viva, but not built). The project deliberately uses no AWS services; the AWS concepts in the syllabus are related to the equivalent mechanisms that were built.

---

## Module 1: Cloud Product & Platform Engineering

| Syllabus topic | Status | Where / how |
|---|---|---|
| Modular, cloud-native style architecture | Implemented | Layered backend (`api`, `services`, `processing`, `monitoring`, `ai`, `recovery`, `security`, `database`) with a separate stateless dashboard; configuration entirely from environment variables (`backend/app/config.py`), following twelve-factor practice. |
| REST APIs | Implemented | 37 FastAPI endpoints with Pydantic validation, typed responses, pagination and consistent errors (`backend/app/api/`, `docs/API.md`). |
| Service separation | Implemented | Frontend and backend are independent processes and Docker images communicating only over HTTP; the database is a third container (`docker-compose.yml`). |
| Workflow orchestration | Implemented | Explicit-state workflow engine with stages, attempts, retry policy, backoff and failure branches (`backend/app/recovery/workflow.py`). |
| Error handling and reliability | Implemented | Error taxonomy (`processing/errors.py`), retryable vs non-retryable classification, repeated-failure suspension, independent output validation, global exception handlers returning safe messages. |
| Containerisation | Implemented | Multi-target `Dockerfile` (non-root user, health check) and `docker-compose.yml`. |
| CI/CD | Implemented (CI) | GitHub Actions runs the test suite on SQLite and PostgreSQL, checks migrations against models, and builds both images (`.github/workflows/ci.yml`). Continuous deployment is described in `DEPLOYMENT.md` (auto-deploy from the main branch on the hosting platform). |
| Database migrations | Implemented | Alembic (`backend/alembic/`). |
| AWS Lambda | Conceptual | Each workflow stage is a small function with a single responsibility; in Lambda each would be an independently scaled function. DataPulse runs them in-process instead. |
| Amazon API Gateway | Conceptual | FastAPI provides routing, request validation, authentication and throttling of sign-in, which are the responsibilities API Gateway takes on in front of Lambda. |
| AWS Step Functions | Conceptual | The workflow engine mirrors a Step Functions state machine: sequential task states, `Retry` with `IntervalSeconds`/`BackoffRate`/`MaxAttempts` (here 0.5 s, ×2, 2 retries) and `Catch` branches that route to failure handling. |

**Demonstration:** run the clean sample with simulated failures (Data ingestion → Failure simulation) and show the stage track with retries, then show `workflow.py` and the GitHub Actions run.

---

## Module 2: Data Engineering, Big Data & ML Insights

| Syllabus topic | Status | Where / how |
|---|---|---|
| ETL pipelines | Implemented | Extract → Validate → Transform → Quality → Load (`services/pipeline_service.py`). |
| Data cleaning | Implemented | Header normalisation, type coercion, constraint checks, business-key de-duplication, quarantine with reasons (`processing/cleaner.py`, `processing/validator.py`). |
| Data-quality validation | Implemented | Quality dimensions and score, configurable rules, truncated-input detection, schema drift (`monitoring/metrics.py`, `monitoring/rules.py`). |
| Pandas | Implemented | All processing. |
| Relational storage (warehouse concept) | Implemented | PostgreSQL schema with constraints and indexes; analytical queries for the dashboard and reports (`database/models.py`, `api/analytics.py`). |
| Machine learning | Implemented | Isolation Forest per pipeline with feature engineering, persistence, minimum-history rule and explanation of deviating features (`monitoring/anomaly_detector.py`). |
| Model evaluation | Implemented | Precision, recall, F1, false-positive rate and a contamination ablation on labeled synthetic data (`scripts/evaluate.py`, `docs/evaluation_results.md`). |
| Pipeline analytics | Implemented | Trends, quality over time, incidents by severity/type, CSV/JSON reports. |
| Big Data / Apache Spark / PySpark | Conceptual | The contract, rules and metrics are expressed per column and per row so they translate directly to Spark DataFrame operations. **Local Pandas processing is not distributed big-data processing**, and the project does not claim it is. PySpark is listed as a future enhancement. |
| AWS Glue | Conceptual | Glue would host the transform stage as a managed Spark job with a Data Catalog holding the contract; DataPulse stores the contract in the `pipelines.config` column. |
| Amazon Redshift | Conceptual | Processed outputs would be loaded into a columnar warehouse; DataPulse stores run-level analytics in PostgreSQL and processed records as files. |

**Demonstration:** run `synthetic_sales_missing_duplicates.csv` and walk through the Data quality page (checks, missing by column, quarantine reasons), then present the evaluation tables.

---

## Module 3: Generative AI, Foundation Models & RAG

| Syllabus topic | Status | Where / how |
|---|---|---|
| LLM integration | Implemented | Provider-agnostic client for OpenAI-compatible APIs and Anthropic with timeouts, rate-limit handling and retries (`ai/llm_client.py`). |
| Foundation models | Implemented | Any configured chat model; Sentence Transformers (MiniLM) as the embedding foundation model. |
| Prompt engineering | Implemented | System prompts that constrain the model to supplied evidence, separate facts from hypotheses, forbid commands and require a fixed JSON schema (`ai/diagnosis.py`, `ai/assistant.py`). |
| Structured outputs | Implemented | Pydantic `DiagnosisModel` validates every LLM response; invalid responses fall back safely. |
| Hallucination control | Implemented | Grounding check flags numbers absent from the evidence; system-confirmed facts are generated by code and displayed separately. |
| Embeddings | Implemented | Sentence Transformers with a TF-IDF fallback (`ai/embeddings.py`). |
| FAISS and similarity search | Implemented | `IndexFlatIP` over normalised vectors with a relevance threshold (`ai/rag.py`). |
| RAG | Implemented | Chunking, indexing, retrieval, persistence with manifest and automatic rebuild; retrieved sections are cited in answers. Evaluated with hit@k and MRR. |
| Evidence-grounded incident analysis | Implemented | Analyse button on the AI incident analyst page; assistant answers six question types from stored records. |
| Graceful degradation | Implemented | Everything works without an LLM key, with answers labelled as rule-based. |
| AI agents (tool use) | Conceptual / partial | The assistant routes questions to deterministic "tools" (failed checks, previous-run comparison, incident history, policy lookup). A model-driven agent that chooses read-only tools itself is described as a future enhancement; the project intentionally gives the model no ability to execute actions. |

**Demonstration:** analyse the schema-change incident, show confirmed facts vs hypothesis and the retrieved documents, then ask "Which validation checks failed?" and "Has this happened before?".

---

## Module 4: Cloud Security, Cryptography & Governance

| Syllabus topic | Status | Where / how |
|---|---|---|
| Authentication | Implemented | PBKDF2-HMAC-SHA256 (600k iterations) password hashing, HS256 tokens with expiry, sign-in throttling (`security/authentication.py`, `api/auth.py`). |
| Role-based authorisation | Implemented | viewer / engineer / admin permission map checked on every endpoint (`security/authorization.py`). |
| Encryption | Implemented | Fernet (AES-128-CBC with HMAC-SHA256) for every stored upload and output (`security/encryption.py`); HTTPS and HSTS at the hosting layer. |
| Secret management | Implemented | Environment variables only; production refuses to start without required secrets; LLM key never reaches the frontend. |
| Audit logging | Implemented | Every significant action with user, resource, outcome and IP (`security/audit.py`; Administration page; exportable). |
| Data governance | Implemented | Masking of sensitive columns, restricted record downloads, retention policy (`services/retention.py`), synthetic data labelling, quarantine instead of deletion. |
| Secure recovery | Implemented | Policy catalogue, approval for data-changing actions, idempotency, retry limits, no execution of model output (`services/recovery_service.py`). |
| Application security | Implemented | Input validation, safe filenames, no code execution of uploads, security headers, safe error messages, CORS configuration. |
| AWS IAM | Conceptual | The permission map implements least privilege per role, as IAM policies do per principal. |
| AWS KMS | Conceptual | `DATA_ENCRYPTION_KEY` plays the role of a data key; KMS would add managed rotation and envelope encryption. |
| CloudTrail | Conceptual | The `audit_logs` table records API activity per user, as CloudTrail records AWS API calls. |
| CloudWatch | Conceptual | Structured logs, `/health`, run metrics and the dashboard provide the monitoring CloudWatch metrics and alarms would provide. |
| VPC / network isolation | Conceptual / partial | In Docker Compose the database is reachable only on the internal network; in hosting, the database should accept connections only from the backend. |

**Demonstration:** sign in as viewer and show masked records and disabled actions; as engineer request a column mapping (pending); as admin approve it; open the audit log.

---

## Summary

| Module | Implemented highlights | Covered conceptually |
|---|---|---|
| 1. Cloud Product & Platform Engineering | REST API, modular services, workflow engine with retries, Docker, CI | Lambda, API Gateway, Step Functions |
| 2. Data Engineering, Big Data & ML | ETL, data quality, PostgreSQL analytics, Isolation Forest with evaluation | Spark/PySpark, Glue, Redshift |
| 3. Generative AI, Foundation Models & RAG | LLM client, prompts, structured outputs, grounding, embeddings, FAISS RAG | Autonomous tool-using agent |
| 4. Cloud Security & Governance | Auth, RBAC, encryption at rest, audit, masking, retention, secure recovery | IAM, KMS, CloudTrail, CloudWatch, VPC |
