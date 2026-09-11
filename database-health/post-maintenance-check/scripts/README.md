# Scripts: Post-Maintenance Health Check

Execution order, safety classification, and expected runtime for every script
in `database-health/post-maintenance-check/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_instance_topology_and_uptime.sql` | Writer/reader role and Aurora cluster topology/lag after maintenance. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_replication_lag_after_maintenance.sql` | Post-maintenance reader lag, for baseline comparison. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_connection_recovery_check.sql` | Connection headroom and per-application connection counts after maintenance. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_blocking_and_lock_check.sql` | Currently blocked sessions and their blockers, after maintenance. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_vacuum_and_xid_status.sql` | In-flight vacuum workers and per-database XID age after maintenance. | READ ONLY | Low (sub-second to a few seconds) |
| 06 | `06_settings_and_extension_verification.sql` | Post-maintenance configuration and extension inventory, for baseline comparison. | READ ONLY | Low (sub-second to a few seconds) |
| 07 | `07_query_performance_vs_baseline.sql` | Post-maintenance top-query comparison (pg_stat_statements). | READ ONLY | Low (sub-second to a few seconds) |

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

- Reader lag has not started converging back toward the pre-maintenance baseline within the expected recovery interval.
- A configuration setting or extension version differs from the baseline in a way that was not part of the planned change.
- Any statement on the order-placement, balance-check, withdrawal, or settlement path is measurably slower than its pre-maintenance baseline.
- XID age on any table did not improve as expected after maintenance that was supposed to include a vacuum pass, or is now closer to the wraparound threshold than before the window opened.

## Scripts That Should Not Be Run During Severe Incidents

_All scripts in this workflow are lightweight, read-only, and safe to run even during a severe incident. Prefer the narrower/most targeted script first if the system is under extreme load._
