# Schema Changes and Schema Drift

Schema drift is any change in the structure of incoming data relative to the pipeline contract: added columns, removed columns, renamed columns, or changed data types.

## Breaking versus non-breaking changes

A removed or renamed required column is a breaking change and stops the run. An added column is usually non-breaking: DataPulse AI processes the declared columns, ignores the extra ones, and opens a medium-severity schema drift incident so the change is reviewed rather than silently absorbed. A type change, such as a numeric price arriving as text with a currency symbol, appears as type validation failures.

## Investigation checklist

Check whether the source system had a release or configuration change on the date of the first affected run. Look at whether previous runs of the same pipeline had the same columns. Ask whether new columns carry information the business needs; if so, the pipeline contract should be extended deliberately.

## Recommended practice

Treat the pipeline contract as versioned. Agree changes with data producers in advance, validate headers before transforming data, and prefer explicit mappings over automatic guessing. Never let a model or heuristic rename columns without human approval, because a wrong mapping corrupts every downstream report.
