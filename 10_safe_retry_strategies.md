# Safe Retry Strategies

Retrying is the right response to transient failures and the wrong response to deterministic ones. A safe retry strategy distinguishes the two and limits the damage of getting it wrong.

## Principles

Only retry errors classified as transient, such as connection resets and timeouts. Use exponential backoff so a struggling dependency is not overwhelmed. Enforce a hard retry limit. Make operations idempotent so a retry cannot duplicate data. Record every attempt with its error and delay.

## What not to retry

Do not retry schema mismatches, missing columns, truncated input files, invalid data or code defects. The input or code must change first; retrying only repeats the failure and hides the real cause.

## Repeated failures

When a pipeline fails repeatedly within a short window, the cause is persistent. DataPulse AI opens a repeated-failure incident and suspends automatic retries for that pipeline until the incident is reviewed.

## Human approval and automation boundaries

Recovery actions that change how data is interpreted, such as column mappings, require administrator approval. The AI assistant can recommend actions in plain language, but only predefined recovery actions can be executed, and only by authorised users. Shell commands, configuration changes and permission changes are never executed from AI output.
