# Scripts: Planner Statistics Maintenance

Execution order, safety classification, and expected runtime for every script
in `maintenance/statistics-maintenance/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_statistics_drift_ranking.sql` | Ranks tables by how far their contents have drifted since the last ANALYZE, which is the primary input to every other decision in this workflow. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_per_table_autovacuum_and_analyze_settings.sql` | Shows which tables already carry per-table autovacuum/analyze storage parameter overrides, alongside their current size and churn, so tuning decisions build on what is already configured. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_column_targets_and_extended_statistics.sql` | Lists non-default per-column statistics targets and every extended (multi-column) statistics object, so correlated-column tuning is visible and not duplicated. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_statistics_maintenance_runbook.md` | Guarded runbook for applying the statistics maintenance actions this workflow identifies: targeted ANALYZE, per-table thresholds, statistics targets, and extended statistics. | LOW RISK WRITE (ANALYZE and statistics DDL; SHARE UPDATE EXCLUSIVE locks with a brief ACCESS EXCLUSIVE for column-level DDL, no table rewrite -- see per-step notes) | Seconds for the DDL steps; minutes to tens of minutes for an ANALYZE of a very large table. |

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

- A table shows extreme drift and its last_autoanalyze is NULL or very old despite autovacuum being enabled -- this is an autovacuum capacity problem, not a statistics problem, and belongs with vacuum-and-autovacuum/autovacuum-not-keeping-up.
- A plan regression persists on the hot trading path immediately after a successful targeted ANALYZE -- statistics are not the cause; escalate to query-optimization/query-regression.

## Scripts That Should Not Be Run During Severe Incidents

- 04_statistics_maintenance_runbook.md -- Real I/O for the duration of each ANALYZE on a large table; brief lock acquisition for the DDL steps, which can queue behind a long-running transaction if lock_timeout is not set.
