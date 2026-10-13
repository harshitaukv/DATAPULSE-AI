# Missing Values

Missing values are empty, null or placeholder entries in fields that should be populated. DataPulse AI treats empty strings and the literal values null, none and nan as missing.

## Impact

A row missing a required field cannot be trusted for reporting. A missing price makes revenue unknown; a missing customer identifier breaks customer-level analysis; a missing region distorts regional dashboards.

## Detection and thresholds

The quality engine counts missing values per column and the share of rows with at least one missing required value. If the overall missing rate or any single required column exceeds the configured threshold (5% by default), a data-quality incident is opened. A single column with many gaps often indicates a mapping or extraction problem rather than random data-entry errors.

## Handling strategy

Rows missing required values are quarantined with a reason such as "missing unit_price". Required fields are never imputed automatically, because inventing values for identifiers or amounts creates false data. Optional descriptive fields may be defaulted if the business agrees and the rule is documented.

## Resolution steps

Review the missing-by-column breakdown in the quality report. If one column dominates, check that column's source mapping and recent changes. Ask the source owner to backfill and re-deliver, then re-run the pipeline with the corrected dataset.
