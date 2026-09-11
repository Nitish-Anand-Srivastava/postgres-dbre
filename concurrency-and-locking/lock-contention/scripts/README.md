# Scripts: Lock Contention

Execution order, safety classification, and expected runtime for every script
in `concurrency-and-locking/lock-contention/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_contention_scale_overview.sql` | Quantifies current lock-wait load across the instance as a starting scope check. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_most_contended_relations.sql` | Identifies which specific relations/locks currently have the most waiters. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_ddl_style_locks.sql` | Checks specifically for stronger lock modes (ShareUpdateExclusive/ShareRowExclusive/AccessExclusive) contributing to contention. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_missing_indexes_on_contended_tables.sql` | Checks index coverage on the most contended tables identified in script 02, since a missing index can widen lock scope under row-locking operations. | READ ONLY | Low (sub-second to a few seconds) |

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

- Contention is traced to a fundamental data-model hot spot (e.g. one row representing a single trading pair's global state) -- this typically requires an application/schema redesign decision, escalate to database engineering and application architecture leadership.

## Scripts That Should Not Be Run During Severe Incidents

_All scripts in this workflow are lightweight, read-only, and safe to run even during a severe incident. Prefer the narrower/most targeted script first if the system is under extreme load._
