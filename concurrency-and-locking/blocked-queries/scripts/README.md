# Scripts: Blocked Queries

Execution order, safety classification, and expected runtime for every script
in `concurrency-and-locking/blocked-queries/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_identify_blocked_sessions.sql` | Identifies every session currently blocked, with its blocking pid(s), using the built-in pg_blocking_pids() helper. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_identify_blocking_sessions.sql` | Expands each blocking relationship to show what the blocking session is doing and for how long. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_lock_detail.sql` | Shows the raw lock detail (mode, object, granted state) behind the blocking relationship for precise diagnosis. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_long_running_transactions.sql` | Confirms whether the blocking session is also one of the oldest open transactions on the instance. | READ ONLY | Low (sub-second to a few seconds) |

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

- The blocking session belongs to a system/replication process rather than application code -- escalate to database engineering before terminating anything.
- The blocking chain does not resolve after the identified blocker is handled (a second, hidden blocker exists) -- escalate for a deeper investigation.

## Scripts That Should Not Be Run During Severe Incidents

_All scripts in this workflow are lightweight, read-only, and safe to run even during a severe incident. Prefer the narrower/most targeted script first if the system is under extreme load._
