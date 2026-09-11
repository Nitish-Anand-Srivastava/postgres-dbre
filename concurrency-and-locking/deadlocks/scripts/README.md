# Scripts: Deadlocks

Execution order, safety classification, and expected runtime for every script
in `concurrency-and-locking/deadlocks/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_deadlock_counters.sql` | Confirms deadlocks are occurring and quantifies frequency per database since the last stats reset. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_current_lock_graph.sql` | Captures the current lock graph, in case a near-deadlock (a long circular wait about to be detected) is actively forming. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_transaction_age_of_contended_sessions.sql` | Checks transaction age for currently active/blocked sessions, to identify which transactions have been open long enough to plausibly be involved in repeated deadlock cycles. | READ ONLY | Low (sub-second to a few seconds) |

## Execution Order

Run scripts strictly in the numeric order shown above. Each script assumes the
operator has reviewed the output of the prior step. Do not skip ahead to a
remediation template (`.md` files, if present) without completing the
read-only investigation steps first.

## Required Permissions

Unless a script states otherwise in its `REQUIRED PRIVILEGES` header field, a
role with the built-in `pg_monitor` (or `pg_read_all_stats` /
`pg_read_all_settings`) attribute, `CONNECT` on the target database, and
`USAGE` on `public` is sufficient. Scripts that read `pg_stat_statements`
require that extension to be installed in the current database. Scripts that
touch DDL, `pg_terminate_backend()`, or write operations state elevated
requirements explicitly in their own header.

## Expected Output

Every script returns a result set intended to be read directly in `psql` (or
any SQL client). Columns are named for direct interpretation; each script's
header contains a `HOW TO INTERPRET RESULTS` section, and the parent
`README.md` section 8 ("Interpretation Guide") gives workflow-level guidance.

## When to Stop and Escalate

- Deadlock rate increases sharply after a deployment -- escalate to the deploying team with the log evidence immediately.
- Deadlocks involve core ledger/balance tables -- escalate to database engineering leadership given the financial-integrity sensitivity even if the application retry logic is confirmed correct.

## Scripts That Should Not Be Run During Severe Incidents

_All scripts in this workflow are lightweight, read-only, and safe to run even during a severe incident. Prefer the narrower/most targeted script first if the system is under extreme load._
