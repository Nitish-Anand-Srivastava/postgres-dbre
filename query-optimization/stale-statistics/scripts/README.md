# Scripts: Stale Planner Statistics

Execution order, safety classification, and expected runtime for every script
in `query-optimization/stale-statistics/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_statistics_freshness_ranked.sql` | Tables ranked by statistics drift. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_analyze_counters_and_never_analyzed.sql` | Analyze history and never-analyzed tables. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_autoanalyze_configuration.sql` | Autoanalyze configuration and per-table overrides. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_stored_statistics_for_table.sql` | Stored distribution statistics for a suspect table. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_refresh_statistics_safely.md` | Guarded ANALYZE runbook for refreshing stale statistics. | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) | Seconds on a small table; minutes on a multi-hundred-gigabyte table. |

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

- A table is so large that a full ANALYZE has a material I/O cost and needs a scheduled window.
- Statistics go stale again within hours of every refresh, meaning the write rate has outgrown the current autoanalyze configuration entirely.
- A plan regression persists after fresh, correctly-sized statistics -- escalate to cardinality-estimation and then to analyze-query-plan.

## Scripts That Should Not Be Run During Severe Incidents

- 05_refresh_statistics_safely.md -- ANALYZE takes a SHARE UPDATE EXCLUSIVE lock (does not block reads or writes) and reads a sample of the table, which is real storage I/O on a very large table. ALTER TABLE ... SET takes a brief ACCESS EXCLUSIVE lock.
