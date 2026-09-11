# Query Plan Regression

**Category:** Performance Issues | **Workflow:** `performance/query-regression`

## 1. Problem Description

A previously well-performing query has recently become significantly slower, without any obvious application-level change -- typically caused by a changed execution plan (index drop, statistics change, data skew, parameter value, or a PostgreSQL/Aurora minor version upgrade) rather than a change in the query text itself.

## 2. Typical Symptoms

- A specific queryid's mean_exec_time in pg_stat_statements has increased sharply compared to prior weeks.
- APM shows a step-change (not gradual) increase in latency for a specific database call, correlated with a deploy, ANALYZE, index change, or maintenance window.

## 3. Business Impact

- Plan regressions on hot paths can silently double or 10x latency for a specific operation while overall system metrics look fine, hiding in aggregate dashboards.
- Left unresolved, a regressed plan can eventually saturate CPU/IO as call volume grows, escalating into a broader high-cpu/high-database-load incident.

## 4. Possible Root Causes

- An index was dropped or became invalid (failed CONCURRENTLY build) removing the planner's best access path.
- A recent ANALYZE picked up a data distribution change (e.g. a new highly skewed status value) that flips the planner's chosen join order or scan method.
- Data growth crossed a threshold where a previously-efficient nested loop plan is no longer efficient.
- A minor engine version upgrade changed planner defaults or cost model behavior (rare, but documented in Aurora PostgreSQL release notes).
- A parameterized/prepared statement is using a generic plan unsuited to the actual parameter value distribution (parameter sniffing).

## 5. Investigation Strategy

1. Confirm the regression is real and quantify it: compare current mean_exec_time against pg_stat_statements' longer-window history if available, or against APM history.
2. Check whether any index the query likely depends on is missing, invalid, or was recently dropped.
3. Check statistics freshness/last_analyze timing against the regression's onset time.
4. Check current table size/row counts against what the query's original plan assumed.
5. Obtain a current EXPLAIN and compare its shape (scan types, join order) against a known-good historical plan if one was saved.
6. Check for a correlated deployment, migration, or maintenance event around the regression's onset.

## 6. Prerequisites

- pg_stat_statements extension created in the target database.
- Ideally, a previously captured 'known good' EXPLAIN plan or pg_stat_statements queryid history to compare against (see query-optimization/query-plan-regression for a template to store these going forward).

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_pgss_regression_candidates.sql`](scripts/01_pgss_regression_candidates.sql) -- Ranks statements by mean execution time and call volume to identify candidate regressions and quantify their current cost.
2. [`scripts/02_invalid_or_missing_indexes.sql`](scripts/02_invalid_or_missing_indexes.sql) -- Checks for invalid indexes on the affected table(s), the single most common direct cause of a sudden plan regression.
3. [`scripts/03_statistics_freshness.sql`](scripts/03_statistics_freshness.sql) -- Checks whether recent ANALYZE activity coincides with the regression's onset, and how much the table has changed since.
4. [`scripts/04_table_size_growth.sql`](scripts/04_table_size_growth.sql) -- Checks current table and index sizes to assess whether data growth alone could explain a plan flip (e.g. nested loop no longer viable).
5. [`scripts/05_sequential_scans.sql`](scripts/05_sequential_scans.sql) -- Confirms whether the regressed query's table(s) are now being scanned sequentially where an index scan would be expected.

## 8. Interpretation Guide

- A sudden step-change correlated with a deploy timestamp points to schema/index changes in that deploy; a gradual drift over days/weeks points to data growth or bloat.
- If the invalid-indexes check (script 02) shows an invalid index on this query's table, that is very likely the direct cause -- a previous CREATE INDEX CONCURRENTLY failed and was never retried.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If an index was dropped or is invalid, restore it via CREATE INDEX CONCURRENTLY (see schema-changes/concurrent-index-build).
- If a specific bad parameter value is triggering a generic/bad plan for a prepared statement, consider `SET plan_cache_mode = force_custom_plan` for that session/role as a stopgap (session-level, not cluster-wide).

**Short-term remediation** (hours to days):

- Run a targeted ANALYZE on the affected table(s) with an increased statistics target for the specific skewed column if data skew is the cause.
- Add an index or rewrite the query if data growth has fundamentally changed the optimal plan.

**Long-term engineering fix** (days to weeks):

- Adopt a plan-regression detection process: periodically snapshot pg_stat_statements per queryid and alert on sustained mean_exec_time increases (see automation/health-checks).
- Add invalid-index detection to routine health checks (database-health/daily-health-check) so a failed CONCURRENTLY build is caught within a day, not discovered via a regression.

## 10. Production Safety

- Investigation scripts are read-only.
- Do not rebuild indexes with plain CREATE INDEX / DROP INDEX on a live production table -- always use the CONCURRENTLY variants per schema-changes/concurrent-index-build.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Regression correlates with an Aurora engine minor-version upgrade -- escalate to AWS Support with the before/after EXPLAIN plans attached.
- No root cause identified after completing this workflow and the query is on a critical path -- escalate to database engineering leadership.

## 12. Related Issues

- [slow-queries](../slow-queries/README.md)
- [performance-after-deployment](../performance-after-deployment/README.md)
- [query-plan-regression](../../query-optimization/query-plan-regression/README.md)
- [invalid-indexes](../../tables-and-indexes/invalid-indexes/README.md)
