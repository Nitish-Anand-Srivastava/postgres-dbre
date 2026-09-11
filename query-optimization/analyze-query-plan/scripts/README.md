# Scripts: Analyze a Query Plan

Execution order, safety classification, and expected runtime for every script
in `query-optimization/analyze-query-plan/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_identify_statement_by_total_time.sql` | Top statements by cumulative execution time. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_statement_latency_profile.sql` | Mean, stddev, and max execution time per statement. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_planning_vs_execution_time.sql` | Planning time vs execution time per statement. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_planner_configuration.sql` | Planner and executor configuration snapshot. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_target_table_indexes_and_statistics.sql` | Index inventory and statistics freshness for the target table. | READ ONLY | Low (sub-second to a few seconds). |
| 06 | `06_capture_plan_safely.md` | Guarded EXPLAIN / EXPLAIN ANALYZE capture runbook. | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) | Mode 1: milliseconds. Mode 2: at least the statement's normal execution time. Mode 3: the same, plus lock hold time. |

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

- The plan is understood but the fix requires a schema change to a hot exchange table (a new index on orders, ledger_entries, or wallets) -- escalate to schema-changes for a safe rollout plan.
- The statement cannot be made acceptably fast without an application-side change to its shape, pagination, or caching strategy.
- The plan is correct and the statement is simply doing too much work for the data volume -- escalate to a partitioning or archival conversation rather than continuing to tune.
- A plan regression is suspected rather than a persistently bad plan -- switch to the query-plan-regression workflow, which is built around before/after comparison.

## Scripts That Should Not Be Run During Severe Incidents

- 06_capture_plan_safely.md -- Mode 1 has no impact. Mode 2 consumes the same resources as one full execution of the statement. Mode 3 additionally takes row locks, generates WAL, and creates dead tuples even though the change is rolled back.
