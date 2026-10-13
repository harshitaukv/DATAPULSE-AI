# ETL Stage Failures

An ETL run in DataPulse AI passes through five stages: extract, validate, transform, quality and load. A failure in any stage stops the run, marks later stages as skipped, and preserves the stage log with the error type and message.

## Reading the stage log

The stage log shows each stage's status, duration and every attempt. The failed stage tells you where to look: extract failures are about reading or parsing the file, validate failures are schema or completeness problems, transform failures are bugs or unexpected data shapes in transformation logic, quality failures are rare and indicate monitoring issues, and load failures are usually storage or database availability problems.

## Non-transient transformation failures

A transformation that fails because of a code defect or an unsupported expression will fail identically on every retry. These failures are not retried automatically. The logs are preserved and the incident is routed for investigation.

## Safe re-runs

Re-running a pipeline is safe in DataPulse AI because each run writes its own output files identified by the run ID, and the original upload is never modified. After fixing the cause, re-run with the same or a corrected dataset and confirm that output validation passes.
