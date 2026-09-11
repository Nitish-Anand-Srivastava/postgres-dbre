# Scripts: Autovacuum Not Keeping Up

Execution order, safety classification, and expected runtime for every script
in `vacuum-and-autovacuum/autovacuum-not-keeping-up/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_dead_tuples_ranked.sql` | Ranks tables by dead tuple count and ratio to find the worst autovacuum-lag offenders. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_current_autovacuum_workers.sql` | Shows currently running autovacuum workers and their progress. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_blocking_transactions.sql` | Checks for long-running transactions that could be preventing autovacuum from reclaiming space it has already identified as dead. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_autovacuum_configuration.sql` | Snapshots current autovacuum cost/worker configuration to assess whether tuning is the root cause. | READ ONLY | Low (sub-second to a few seconds) |

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

- Bloat continues to grow despite tuning changes and manual vacuum -- escalate to database engineering for a schema/partitioning-level fix.

## Scripts That Should Not Be Run During Severe Incidents

_All scripts in this workflow are lightweight, read-only, and safe to run even during a severe incident. Prefer the narrower/most targeted script first if the system is under extreme load._
