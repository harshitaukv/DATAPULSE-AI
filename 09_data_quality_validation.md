# Data Quality Validation

Data quality validation checks that a dataset is complete, unique, valid and consistent with its contract before it is used for reporting.

## Quality dimensions

Completeness measures whether required fields are populated. Uniqueness measures whether each business event appears once. Validity measures whether values satisfy type and business rules. Schema conformance measures whether the structure matches the agreed contract.

## Quality score

DataPulse AI combines these into a score from 0 to 100: 30% completeness, 25% uniqueness, 35% validity and 10% schema conformance. The score is a summary for trend monitoring; the individual metrics and the quarantine report are the evidence to act on.

## Quarantine instead of deletion

Rejected rows are written to a quarantine file with their source row number and the reasons for rejection. The original upload is preserved and encrypted at rest. This makes every cleaning decision reviewable and reversible.

## Volume and baseline checks

Quality also includes whether the expected amount of data arrived. Record counts are compared with the median of recent completed runs. With fewer than the minimum number of historical runs, no volume judgement is made and the report says the history is insufficient.
