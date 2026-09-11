# Scripts: Capacity Health Check

Execution order, safety classification, and expected runtime for every script
in `database-health/capacity-health-check/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_database_and_table_footprint.sql` | Database sizes and largest tables by total size. | READ ONLY | Low to moderate (seconds; longer on schemas with many thousands of partitions). |
| 02 | `02_table_growth_trend.sql` | Table growth over the tracked window, where a growth-history table exists. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_connection_capacity_headroom.sql` | Connection utilization and per-application connection counts. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_io_and_checkpoint_pressure.sql` | I/O statistics by backend type, plus checkpoint and background-writer activity. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_replication_slot_wal_retention.sql` | Replication slots and their retained WAL, against a documented threshold. | READ ONLY | Low (sub-second to a few seconds) |
| 06 | `06_temp_file_and_index_footprint.sql` | Temp file usage per database and largest indexes. | READ ONLY | Low (sub-second to a few seconds) |
| 07 | `07_key_capacity_settings.sql` | Key configuration settings relevant to capacity planning. | READ ONLY | Low (sub-second to a few seconds) |

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

- Connection utilization above 85% with no clear path to reduce per-service pool sizes -- escalate to connections/max-connections-planning before the next high-volume event.
- A replication slot retaining tens of gigabytes or more of WAL with no active consumer -- escalate immediately, this is unattributed storage growth with a clear owner question attached.
- Storage growth on a table not explained by expected business volume (a reference or configuration table appearing among the largest tables) -- escalate to investigate a bug or unintended accumulation.
- Checkpoint or buffer I/O pressure rising for several consecutive reviews while row counts alone do not explain the increase -- escalate to storage-and-capacity/wal-generation.

## Scripts That Should Not Be Run During Severe Incidents

_All scripts in this workflow are lightweight, read-only, and safe to run even during a severe incident. Prefer the narrower/most targeted script first if the system is under extreme load._
