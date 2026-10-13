# Database Connection Errors

Connection errors occur when the pipeline cannot reach or keep a connection to its database or storage layer. Examples include connection refused, connection reset by peer, server closed the connection unexpectedly, and too many connections.

## Transient versus persistent

Most connection errors are transient: a database restart, a failover, a brief network partition, or a full connection pool. These usually succeed when retried after a short delay. Persistent errors such as wrong credentials, a deleted database, or a firewall rule will fail every time and must not be retried endlessly.

## Automatic handling

DataPulse AI classifies connection and timeout errors as retryable. The affected stage is retried with exponential backoff (for example 0.5 seconds, then 1 second) up to the configured retry limit. Every attempt is written to the recovery history. If a retry succeeds, the output is validated before the incident is marked resolved.

## When retries are exhausted

If the retry limit is reached, the run fails and the incident requires manual attention. Check that the database is running, that the connection string in DATABASE_URL is correct, that credentials have not expired, and that the connection pool size is adequate. After repeated failures automatic retries are suspended for the pipeline until someone reviews it.
