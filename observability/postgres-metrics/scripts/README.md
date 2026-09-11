# Scripts: Native PostgreSQL Metrics Worth Monitoring Continuously

Execution order, safety classification, and expected runtime for every script
in `observability/postgres-metrics/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_connection_and_session_metrics.sql` | Session state distribution and connection headroom. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_database_throughput_and_cache_metrics.sql` | Per-database throughput, cache hit ratio, rollbacks, deadlocks, and temp file counters. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_table_and_index_activity_metrics.sql` | Per-table dead tuple ratios and per-index size/scan activity. | READ ONLY | Low to moderate (seconds; scales with the number of tables/indexes in the database). |
| 04 | `04_io_and_checkpoint_metrics.sql` | I/O by backend type, checkpoint activity, and background-writer activity. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_wal_generation_metrics.sql` | Cluster-wide WAL generation counters, or an Aurora availability notice. | READ ONLY | Low (sub-second to a few seconds) |

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

- This workflow does not itself define escalation thresholds -- each metric's escalation criteria lives in the workflow that owns that failure mode (see Related Issues).
- If auditing an existing pipeline surfaces a complete gap in an entire metric family (for example, no vacuum/XID visibility at all), treat closing that gap as urgent infrastructure work, not a backlog item -- it is the same gap that turns a slow-moving problem into a surprise incident.

## Scripts That Should Not Be Run During Severe Incidents

_All scripts in this workflow are lightweight, read-only, and safe to run even during a severe incident. Prefer the narrower/most targeted script first if the system is under extreme load._
