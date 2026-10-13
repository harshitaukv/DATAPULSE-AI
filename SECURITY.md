# Security notes

## Implemented

- Password hashing with PBKDF2-HMAC-SHA256, 600,000 iterations, random salt per user; constant-time comparison; equalised timing for unknown users.
- Signed access tokens (HS256) with expiry; every request re-checks that the user still exists and is active.
- Role-based access control on every endpoint (viewer, engineer, admin).
- Sign-in throttling: five failed attempts for a username within five minutes block further attempts for that window.
- Encryption at rest for uploaded datasets and generated outputs (Fernet).
- Masking of sensitive columns (`SENSITIVE_COLUMNS`, default `customer_id`) in previews and quarantine samples; unmasked record downloads limited to administrators and the engineer who ran the pipeline.
- Upload validation: extension allow-list, size limit enforced while streaming, binary and encoding checks, structural parsing, filename sanitisation. Uploaded content is never executed; derived columns use whitelisted expressions only.
- Recovery restricted to a catalogue of actions; data-changing actions need administrator approval; the LLM cannot execute anything.
- Audit log of sign-ins (including failures and lock-outs), uploads, runs, analyses, recovery requests and decisions, downloads, exports, deletions, user creation and index rebuilds.
- Safe error handling: generic messages, no stack traces, paths or database details in responses; 503 when the database is unreachable.
- Security headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Cache-Control: no-store`; HSTS in production); configurable CORS; API docs disabled in production.
- Secrets only from environment variables; production mode refuses to start without `SECRET_KEY`, `DATA_ENCRYPTION_KEY` and `DATABASE_URL`; `.env` is git-ignored.
- Data retention: files older than `RETENTION_DAYS` can be deleted (dry run by default) while metadata is retained.
- Containers run as a non-root user; the database is not exposed outside the Compose network.

## Not production-ready (known gaps)

- **Throttling state is in memory.** It resets on restart and is per process; use a shared store (for example Redis) or a reverse-proxy rate limiter for multi-instance deployments.
- **No token revocation or refresh tokens.** Signing out clears the session in the dashboard, but an issued token stays valid until it expires. Shorten `ACCESS_TOKEN_EXPIRE_MINUTES` or add a deny-list for production.
- **No multi-factor authentication, password reset or single sign-on.**
- **Development fallbacks.** Without `SECRET_KEY`, development mode generates an ephemeral key; without `DATA_ENCRYPTION_KEY` it stores a key in `data/.dev_encryption_key` next to the data it protects. Both are acceptable only for local development.
- **Key rotation is manual.** Changing `DATA_ENCRYPTION_KEY` makes previously stored files unreadable unless they are re-encrypted; a managed key service with envelope encryption would solve this.
- **The dashboard's own transport** depends on the hosting platform providing HTTPS.
- **Rate limiting of general API traffic and LLM calls** is not implemented beyond sign-in; set provider-side spending limits for the LLM key.
- **Dependency scanning** (for example `pip-audit`) is not yet part of CI.
