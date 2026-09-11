# Scripts: Query Plan Regression

Execution order, safety classification, and expected runtime for every script
in `query-optimization/query-plan-regression/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_latency_distribution_by_statement.sql` | Latency distribution and variance per statement. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_planning_time_check.sql` | Planning time and generic-plan configuration. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_statistics_change_check.sql` | Statistics refresh timing on the involved tables. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_index_state_check.sql` | Invalid indexes and index usage state. | READ ONLY | Low to moderate (seconds; scales with the number of indexes). |
| 05 | `05_configuration_drift_check.sql` | Planner and memory configuration drift check. | READ ONLY | Low (sub-second to a few seconds) |
| 06 | `06_plan_baseline_comparison.md` | Guarded runbook for plan baseline comparison and creation. | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) | Step 1: milliseconds. Step 2: up to the configured statement_timeout. |

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

- A regression affects order placement, balance checks, withdrawals, or settlement -- escalate immediately and evaluate rollback in parallel with diagnosis.
- pg_stat_statements was reset (typically by a failover) and no stored baseline exists, so the regression cannot be confirmed from database evidence -- escalate to reconstruct it from application-side latency metrics.
- The plan reverts to the bad shape after every remediation, indicating a deeper estimation problem -- escalate to cardinality-estimation.

## Scripts That Should Not Be Run During Severe Incidents

- 06_plan_baseline_comparison.md -- Step 1 and baseline capture: none, EXPLAIN does not execute the statement. Step 2: a full execution of the statement, bounded by statement_timeout.
