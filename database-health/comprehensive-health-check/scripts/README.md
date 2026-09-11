# Scripts: Comprehensive Database Health Check

Execution order, safety classification, and expected runtime for every script
in `database-health/comprehensive-health-check/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_instance_identity_and_uptime.sql` | Instance identity, engine version, writer/reader role, and uptime. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_database_and_table_sizes.sql` | Database sizes plus the largest tables by total size. | READ ONLY | Low to moderate (seconds; longer on schemas with many thousands of partitions). |
| 03 | `03_database_activity_counters.sql` | Per-database throughput, cache hit ratio, rollbacks, deadlocks, and temp file counters. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_connection_headroom_and_state.sql` | Connection utilization vs max_connections, and sessions by state. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_open_transaction_horizon.sql` | Oldest open transactions plus outstanding prepared transactions. | READ ONLY | Low (sub-second to a few seconds) |
| 06 | `06_blocking_and_lock_waits.sql` | Currently blocked sessions and their blockers. | READ ONLY | Low (sub-second to a few seconds) |
| 07 | `07_dead_tuples_and_vacuum_status.sql` | Tables ranked by dead tuples, with last vacuum/analyze timestamps. | READ ONLY | Low (sub-second to a few seconds) |
| 08 | `08_autovacuum_activity.sql` | Currently running vacuum workers and their progress. | READ ONLY | Low (sub-second to a few seconds) |
| 09 | `09_transaction_id_age.sql` | Per-database XID age vs the wraparound thresholds. | READ ONLY | Low (sub-second to a few seconds) |
| 10 | `10_top_queries_by_total_time.sql` | Top statements by cumulative execution time (pg_stat_statements). | READ ONLY | Low (sub-second to a few seconds) |
| 11 | `11_temp_file_usage.sql` | Cumulative temp file usage per database. | READ ONLY | Low (sub-second to a few seconds) |
| 12 | `12_index_usage_overview.sql` | Index size and scan-activity inventory. | READ ONLY | Low to moderate (seconds; scales with the number of indexes in the database). |
| 13 | `13_replication_and_reader_health.sql` | Aurora cluster replica status and lag. | READ ONLY | Low (sub-second to a few seconds) |

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

- XID age above 1,000,000,000 in any database, or above 50% of autovacuum_freeze_max_age and still rising between two runs -- escalate immediately to transactions-and-xid/xid-wraparound-risk.
- Connection utilization above 90% of max_connections on the writer -- escalate to connections/connection-exhaustion before it becomes a full outage.
- A prepared transaction older than a few minutes, or a replication slot retaining tens of gigabytes of WAL -- both silently block cleanup cluster-wide and need an owner identified immediately.
- Any finding that implicates the ledger, wallet, or settlement tables' correctness (not just their performance) -- escalate to database engineering and the finance/treasury on-call together.

## Scripts That Should Not Be Run During Severe Incidents

_All scripts in this workflow are lightweight, read-only, and safe to run even during a severe incident. Prefer the narrower/most targeted script first if the system is under extreme load._
