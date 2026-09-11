# Scripts: Using AWS Performance Insights Alongside SQL Diagnostics

Execution order, safety classification, and expected runtime for every script
in `observability/performance-insights/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_current_wait_event_snapshot.sql` | Current backend counts by wait event type/name. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_active_session_load_by_query.sql` | Active sessions grouped by query_id and wait event, approximating DB load by SQL. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_enabling_and_interpreting_performance_insights.md` | Runbook: confirm/enable Performance Insights and read its DB load view during an investigation. | LOW RISK WRITE (AWS instance configuration change to enable Performance Insights; no SQL statements executed against the database) | A few minutes to check/enable; the console investigation itself is as long as the incident review requires. |

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

- DB load sustained meaningfully above the instance's vCPU count for an extended period, with no corresponding drop in application throughput explaining it as expected -- escalate to performance/high-database-load.
- PI's Top Waits view is dominated by Lock wait events for more than a few minutes -- escalate to concurrency-and-locking/lock-contention immediately rather than waiting for a live SQL session to confirm it.
- PI shows a load spike that has already ended by the time it is noticed and no live session data remains -- this is exactly the scenario PI exists for; do not conclude 'nothing to investigate' just because a live pg_stat_activity query now looks clean.

## Scripts That Should Not Be Run During Severe Incidents

- 03_enabling_and_interpreting_performance_insights.md -- None -- this is reference/planning documentation, not an executable script. Any AWS-side action it describes (enabling a feature, creating an alarm) is called out explicitly and is a change-managed action outside this repository's SQL scope.
