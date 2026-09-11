# Scripts: High CPU Utilization

Execution order, safety classification, and expected runtime for every script
in `performance/high-cpu/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_identify_database_load.sql` | Cluster-wide session/state overview to establish overall load before drilling in. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_identify_active_queries.sql` | Lists currently active queries running longer than a threshold, to identify what is actively consuming CPU right now. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_identify_expensive_queries.sql` | Top statements by total execution time from pg_stat_statements, to find the historically dominant CPU consumers, not just this instant's snapshot. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_check_wait_events.sql` | Aggregates current wait events to confirm whether load is genuinely CPU-bound vs. lock/IO-bound. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_check_lock_contention.sql` | Confirms or rules out lock contention as a secondary/contributing factor to elevated CPU (e.g. spin-heavy retry logic). | READ ONLY | Low (sub-second to a few seconds) |
| 06 | `06_check_table_index_health.sql` | Checks for sequential-scan-heavy tables and stale statistics that commonly cause CPU-expensive plans. | READ ONLY | Low (sub-second to a few seconds) |

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

- CPU remains >90% for more than 15 minutes despite mitigations, with visible customer-facing latency impact.
- Root cause appears to be outside the database (application bug, retry storm) -- loop in application/SRE teams immediately rather than continuing DB-only investigation.
- Suspected undersized instance class requiring a scaling decision beyond on-call authority.

## Scripts That Should Not Be Run During Severe Incidents

_All scripts in this workflow are lightweight, read-only, and safe to run even during a severe incident. Prefer the narrower/most targeted script first if the system is under extreme load._
