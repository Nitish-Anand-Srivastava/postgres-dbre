# Scripts: Storage Capacity Forecasting

Execution order, safety classification, and expected runtime for every script
in `storage-and-capacity/capacity-forecasting/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_database_size_baseline.sql` | Per-database size baseline. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_relation_size_baseline.sql` | Per-relation size baseline. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_measured_growth_from_history.sql` | Measured growth per relation over the history window. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_linear_projection_and_runway.sql` | Linear size projection and days-to-threshold runway. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_write_rate_projection_proxy.sql` | Fallback growth projection from write rates. | READ ONLY | Low (sub-second to a few seconds) |
| 06 | `06_capacity_forecast_worksheet.md` | Forecast worksheet: inputs, assumptions, thresholds, decisions. | READ ONLY | Not applicable -- documentation worksheet. |

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

- Any projection shows the cluster approaching the Aurora 128 TiB volume limit inside the forecast horizon -- involve AWS support and engineering leadership immediately.
- Projected runway on a business-critical relation is under ninety days, which is less than a realistic partitioning or archival project takes -- this needs prioritization at leadership level, not a DBA backlog ticket.
- Projected storage cost growth exceeds the budgeted envelope -- a finance and engineering decision, not a database one.
- Actual measured growth has diverged sharply from the previous forecast with no known cause -- re-run unexpected-storage-growth before issuing a revised number.

## Scripts That Should Not Be Run During Severe Incidents

- 06_capacity_forecast_worksheet.md -- None -- this file is a documentation worksheet and contains no executable statements.
