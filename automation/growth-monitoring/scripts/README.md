# Scripts: Table Growth History Collector

Execution order, safety classification, and expected runtime for every script
in `automation/growth-monitoring/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_check_tracking_table_status.sql` | Tracking table existence, row count, and capture window. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_verify_collection_cadence.sql` | Gaps between consecutive collection timestamps, largest first. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_growth_rate_from_history.sql` | Per-table growth between the earliest and latest sample in the window. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_deploy_collector_runbook.md` | Collector deployment runbook: schema, table DDL, population query, and scheduling. | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) | Variable -- depends on table size and chosen batch size; see runbook. |

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

- The collector has been down (no new rows) for long enough that a business-critical capacity decision cannot be made from trend data -- treat the immediate priority as restoring collection, and fall back to storage-and-capacity's single-point-in-time scripts for the decision at hand.

## Scripts That Should Not Be Run During Severe Incidents

- 04_deploy_collector_runbook.md -- Varies by step -- read each step's own warning before executing it.
