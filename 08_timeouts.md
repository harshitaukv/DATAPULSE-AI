# Timeouts and Slow Runs

A timeout is an operation that does not finish within its allowed time. A slow run completes, but much later than usual.

## Common causes

Larger than normal input files, resource contention on the host, slow storage, lock waits in the database, and inefficient transformation logic introduced by a recent change are the usual causes. External API calls, including LLM requests, can also time out under load or rate limiting.

## Detection

DataPulse AI compares each run's processing time with the median duration of recent successful runs. A run that exceeds both a multiple of the median (three times by default) and a minimum absolute duration opens a low-severity performance incident.

## Response

A single slow run usually needs monitoring only. Check whether the input volume was unusually high. If slowdowns persist across several runs, profile the transform stage and check host resources. Timeouts on network operations are treated as transient and retried with backoff; LLM timeouts never block data processing because the assistant falls back to deterministic summaries.
