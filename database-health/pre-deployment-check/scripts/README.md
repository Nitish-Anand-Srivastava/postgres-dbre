# Scripts: Pre-Deployment Health Check

Execution order, safety classification, and expected runtime for every script
in `database-health/pre-deployment-check/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_blocking_and_lock_waits.sql` | Currently blocked sessions and their blockers. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_strong_lock_modes_held.sql` | Strong lock modes currently held or waiting. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_long_running_transactions.sql` | Open and idle-in-transaction sessions that would block DDL. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_connection_headroom.sql` | Connection headroom and per-application connection counts. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_replication_lag_baseline.sql` | Reader lag baseline before deployment. | READ ONLY | Low (sub-second to a few seconds) |
| 06 | `06_maintenance_in_flight.sql` | In-flight vacuum/maintenance operations. | READ ONLY | Low (sub-second to a few seconds) |
| 07 | `07_query_performance_baseline.sql` | Pre-deployment top-query baseline (pg_stat_statements). | READ ONLY | Low (sub-second to a few seconds) |

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

- Any blocked session already exists before the deployment starts -- do not add a migration on top of an existing lock chain.
- A transaction has been open longer than the migration's lock_timeout budget and its owner cannot be reached.
- Connection utilization above 80%, leaving no room for the connection churn of a rolling restart.
- Reader lag above its normal baseline, or a failover in the last few minutes -- let the cluster stabilize first.

## Scripts That Should Not Be Run During Severe Incidents

_All scripts in this workflow are lightweight, read-only, and safe to run even during a severe incident. Prefer the narrower/most targeted script first if the system is under extreme load._
