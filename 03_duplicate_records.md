# Duplicate Records

Duplicate records are rows that represent the same business event more than once. For sales data, the business key is the transaction identifier: two rows with the same `transaction_id` are duplicates even if other fields differ slightly.

## Why duplicates appear

Typical causes are overlapping extract windows (yesterday's tail re-sent today), retried uploads that append instead of replace, at-least-once message delivery, and manual re-exports. Duplicates inflate revenue, quantities and counts in every downstream report.

## Detection

DataPulse AI counts rows whose business key has already been seen in the batch. Rows with a missing business key cannot be de-duplicated safely and are quarantined as invalid instead. A duplicate rate above the configured threshold (2% by default) opens a data-quality incident.

## Deduplication policy

The default policy is keep_first: the first occurrence of each business key is kept and later occurrences are moved to the quarantine file with the reason "duplicate business key". Nothing is deleted, so the decision can be reviewed. Deduplication is only applied when the business key is valid. After deduplication the output is re-read and verified to have a unique key.

## Fixing the root cause

Quarantining duplicates repairs the current batch but not the source. Check the extract window boundaries, make loads idempotent (replace by date partition instead of append), and ask the producer whether a replay occurred.
