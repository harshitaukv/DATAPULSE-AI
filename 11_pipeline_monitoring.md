# Pipeline Monitoring and Anomaly Detection

Monitoring answers two questions about each run: did it work, and does it look normal compared with previous runs?

## Rule-based monitoring

Transparent rules with configurable thresholds catch known problems: missing columns, high duplicate, missing or invalid rates, large volume drops or spikes, slow runs and repeated failures. Rules are easy to explain and audit.

## Machine-learning anomaly detection

DataPulse AI also trains an Isolation Forest per pipeline on the history of completed runs, using features such as record count, missing percentage, duplicate percentage, invalid percentage, processing duration and deviation from the baseline volume. It flags runs whose combination of metrics is unusual even when no single rule fires. It requires at least ten historical runs; with less history it reports that history is insufficient instead of guessing.

## Interpreting an anomaly

An anomaly flag means the run is unusual, not that it is wrong. The detector reports which features deviate most. Use that evidence with the rule findings and the business context to decide whether there is a real problem. The model never determines the root cause by itself.

## Comparing with previous runs

To understand what changed, compare the current run's record count, quality score, missing and duplicate rates and schema with the previous run of the same pipeline. Sudden changes that coincide with a source release usually explain the incident.
