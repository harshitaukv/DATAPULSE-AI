# Invalid Data Types and Constraint Violations

Invalid values are present but cannot be interpreted correctly: text in a numeric field, an impossible date, a negative quantity, a zero or negative price, or a category outside the allowed set.

## Typical examples

Common examples are a unit price of "N/A" or "12,50", a quantity of -3, a transaction date of 2026-13-45, and a region of "Atlantis" when only North, South, East, West and Central are allowed. Each is recorded with the rule it violated.

## Invalid versus unusual

An invalid value breaks a declared rule and is quarantined. An unusual value is valid but rare, such as a very large order; it is kept in the output and reported separately. Keeping this distinction prevents legitimate but rare business events from being discarded.

## Diagnosis

Use the type errors by column and constraint violations sections of the quality report. A sudden burst of the same violation in one column usually points to a source format change, for example a locale switch that changed the decimal separator.

## Resolution

Correct the values at the source and re-deliver. If a format change is permanent, update the parsing rules in the pipeline contract through a reviewed change. Do not coerce invalid values silently to zero.
