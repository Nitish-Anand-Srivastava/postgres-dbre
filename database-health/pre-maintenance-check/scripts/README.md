# Scripts: Pre-Maintenance Health Check

Execution order, safety classification, and expected runtime for every script
in `database-health/pre-maintenance-check/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_instance_topology_and_uptime.sql` | Writer/reader role and Aurora cluster topology/lag. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_connection_headroom_and_mix.sql` | Connection headroom and per-application connection counts. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_open_transactions_and_prepared.sql` | Open and prepared transactions that a restart would interrupt. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_replication_lag_baseline.sql` | Reader lag baseline before maintenance. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_vacuum_and_xid_status.sql` | In-flight vacuum workers and per-database XID age. | READ ONLY | Low (sub-second to a few seconds) |
| 06 | `06_settings_and_extension_baseline.sql` | Configuration settings and extension inventory baseline. | READ ONLY | Low (sub-second to a few seconds) |
| 07 | `07_query_performance_baseline.sql` | Pre-maintenance top-query baseline (pg_stat_statements). | READ ONLY | Low (sub-second to a few seconds) |

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

- Any transaction open longer than a few minutes, or any prepared transaction at all, with no owner reachable before the window opens.
- An anti-wraparound autovacuum currently running on a large table -- interrupting it via restart means it restarts its scan from the beginning afterward.
- Reader lag already above the application's normal tolerance, or a failover in the last few minutes -- let the cluster stabilize first.
- Connection utilization above 80%, leaving no headroom for the reconnect storm the operation will cause.

## Scripts That Should Not Be Run During Severe Incidents

_All scripts in this workflow are lightweight, read-only, and safe to run even during a severe incident. Prefer the narrower/most targeted script first if the system is under extreme load._
