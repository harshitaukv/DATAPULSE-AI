# Missing Column Errors

A missing column error occurs when a pipeline stage references a field that is not present in the incoming dataset. In Python ETL code it usually surfaces as `KeyError: 'column_name'`; in DataPulse AI the validate stage catches it earlier and reports a schema mismatch listing the missing required columns.

## Symptoms

The run fails in the validate stage. The incident evidence lists `missing_required` columns, the columns that were actually received, and any unexpected columns. No processed output is written, because transforming a dataset with an incomplete contract would produce misleading results.

## Common causes

The most common cause is an upstream rename: the source system changed `customer_id` to `cust_id` or `CustomerID` during a release. Other causes are a different export template being used, a manual spreadsheet edit that deleted a column, or a delimiter problem that merged several columns into one.

## How to diagnose

Compare the expected columns with the actual columns in the incident evidence. If an unexpected column has a name very similar to the missing one, a rename is likely; DataPulse AI reports these as suggested mappings with a similarity score. If the whole header looks like one long field, check the delimiter and quoting. Confirm the change with the owner of the source system before acting.

## Resolution

If the column was only renamed and the values are the same, apply a column mapping (for example `cust_id -> customer_id`). Column mappings change how data is interpreted, so they require administrator approval and are recorded in the audit log. If the column is genuinely absent, request a corrected file and re-run with the new dataset. Do not invent default values for a required identifier column.
