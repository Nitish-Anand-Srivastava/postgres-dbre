# Scripts: Slow Queries

Execution order, safety classification, and expected runtime for every script
in `performance/slow-queries/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_current_activity.sql` | Snapshot of current session/state activity to confirm whether the reported slow query is still running. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_long_running_queries.sql` | Lists currently active queries beyond a runtime threshold, to catch the slow query if it is still executing. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_pg_stat_statements_top_queries.sql` | Looks up historical call/timing statistics for the query pattern from pg_stat_statements. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_wait_events.sql` | Checks the specific wait event(s) for the backend(s) running the slow query. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_lock_contention.sql` | Checks whether the slow query is blocked by another session. | READ ONLY | Low (sub-second to a few seconds) |
| 06 | `06_table_statistics.sql` | Checks table-level statistics (row counts, dead tuples, last analyze) for the query's target table(s). | READ ONLY | Low (sub-second to a few seconds) |
| 07 | `07_index_usage.sql` | Checks existing index definitions and usage for the query's target table(s). | READ ONLY | Low (sub-second to a few seconds) |
| 08 | `08_execution_plan_guidance.md` | Guidance for safely obtaining and reading an execution plan for the slow query. | DOCUMENTATION -- no SQL is executed by this file itself | Variable -- depends on table size and chosen batch size; see runbook. |

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

- The slow query is on a financial write path (order matching, balance update, ledger write) and cannot be safely cancelled -- escalate to database engineering leadership and the owning application team immediately.
- Root cause is a plan regression correlated with a recent deployment -- cross-link to performance-after-deployment and involve the deploying team.

## Scripts That Should Not Be Run During Severe Incidents

- 08_execution_plan_guidance.md -- None from this file; impact depends entirely on which guidance the operator chooses to execute.
