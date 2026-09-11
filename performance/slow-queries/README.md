# Slow Queries

**Category:** Performance Issues | **Workflow:** `performance/slow-queries`

## 1. Problem Description

One or more specific queries are executing slower than expected, either as isolated incidents reported by an engineering team or as a general pattern surfaced by APM/tracing. This is the general-purpose, query-first investigation workflow; use query-regression instead when you specifically suspect a plan change after a deploy or ANALYZE.

## 2. Typical Symptoms

- A specific API endpoint or batch job reports elevated latency or timeouts.
- APM/tracing shows increased time spent in a database call.
- Customer/internal reports of a specific operation (e.g. order history lookup, balance query) being slow.

## 3. Business Impact

- Slow queries on hot paths (order placement, balance checks, withdrawal processing) directly degrade user experience and can breach internal SLAs.
- Slow queries holding connections/transactions open longer than necessary reduce effective connection pool capacity for all other traffic.

## 4. Possible Root Causes

- Missing or unused index for the query's predicate/join/order-by.
- Stale statistics causing the planner to choose a poor join order or scan method.
- Data growth: a previously fine plan (e.g. nested loop over a small table) no longer suits the current table size.
- Lock contention delaying the query's execution rather than the query itself being computationally expensive.
- Parameter sniffing / generic plan issues with prepared statements and highly skewed data distributions.
- Excessive temp file usage from undersized work_mem for the query's sort/hash/aggregate operations.

## 5. Investigation Strategy

1. Confirm current activity: is the slow query still running, or has it already completed?
2. Identify any currently long-running instances of the query and their exact runtime.
3. Look up the query in pg_stat_statements for historical calls/mean/total time trends.
4. Check wait events for the specific backend(s) running the query.
5. Check for lock contention affecting the query's table(s).
6. Check table-level statistics (dead tuples, last analyze, row counts) for the query's target tables.
7. Check index usage/existence for the query's predicates.
8. Obtain and review the query's execution plan (EXPLAIN, and EXPLAIN ANALYZE only under the safety conditions documented in script 08).

## 6. Prerequisites

- pg_stat_statements extension created in the target database (scripts 03).
- Query text or queryid from the reporting team/APM tool to narrow scripts 03/07/08 to the specific statement.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_current_activity.sql`](scripts/01_current_activity.sql) -- Snapshot of current session/state activity to confirm whether the reported slow query is still running.
2. [`scripts/02_long_running_queries.sql`](scripts/02_long_running_queries.sql) -- Lists currently active queries beyond a runtime threshold, to catch the slow query if it is still executing.
3. [`scripts/03_pg_stat_statements_top_queries.sql`](scripts/03_pg_stat_statements_top_queries.sql) -- Looks up historical call/timing statistics for the query pattern from pg_stat_statements.
4. [`scripts/04_wait_events.sql`](scripts/04_wait_events.sql) -- Checks the specific wait event(s) for the backend(s) running the slow query.
5. [`scripts/05_lock_contention.sql`](scripts/05_lock_contention.sql) -- Checks whether the slow query is blocked by another session.
6. [`scripts/06_table_statistics.sql`](scripts/06_table_statistics.sql) -- Checks table-level statistics (row counts, dead tuples, last analyze) for the query's target table(s).
7. [`scripts/07_index_usage.sql`](scripts/07_index_usage.sql) -- Checks existing index definitions and usage for the query's target table(s).
8. [`scripts/08_execution_plan_guidance.md`](scripts/08_execution_plan_guidance.md) -- Guidance for safely obtaining and reading an execution plan for the slow query.

## 8. Interpretation Guide

- If the query does not appear as currently active and has a low mean_exec_time in pg_stat_statements, the slowness was likely transient (lock wait, connection pool exhaustion, or network) rather than the query plan itself.
- A high stddev_exec_time relative to mean_exec_time in pg_stat_statements indicates inconsistent performance -- often parameter-sensitive plans or lock contention -- rather than a uniformly bad plan.
- Confirm via EXPLAIN whether the planner's row estimates are close to reality; large estimate-vs-actual gaps point to a statistics problem, not an index problem.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If the query is currently running and confirmed safe to cancel (not a financial write in flight), cancel via `pg_cancel_backend` (never `pg_terminate_backend` for a routine slow query) -- see incident-response/runaway-query.
- If lock contention is the cause, resolve the blocking session per concurrency-and-locking/blocked-queries instead of touching the slow query itself.

**Short-term remediation** (hours to days):

- Add a targeted index using CREATE INDEX CONCURRENTLY (see schema-changes/concurrent-index-build).
- Run a targeted ANALYZE on the specific table(s) if statistics are stale (do not ANALYZE the whole database as a blind fix).
- Rewrite the query (e.g. replace an OR-based predicate with a UNION, or restructure a subquery as a join) if the plan is fundamentally suboptimal for the current data shape.

**Long-term engineering fix** (days to weeks):

- Revisit schema/partitioning for tables that are structurally too large for the current query pattern (see partitioning/investigate-partitioning-candidate).
- Add query-shape regression testing/plan monitoring to CI or synthetic canaries so regressions are caught before reaching production.

## 10. Production Safety

- Scripts 01-07 are read-only and safe to run at any time.
- Script 08 is documentation-only guidance and explicitly warns against running EXPLAIN ANALYZE on write statements or unbounded queries in production without safeguards.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- The slow query is on a financial write path (order matching, balance update, ledger write) and cannot be safely cancelled -- escalate to database engineering leadership and the owning application team immediately.
- Root cause is a plan regression correlated with a recent deployment -- cross-link to performance-after-deployment and involve the deploying team.

## 12. Related Issues

- [query-regression](../query-regression/README.md)
- [analyze-query-plan](../../query-optimization/analyze-query-plan/README.md)
- [missing-index-candidates](../../tables-and-indexes/missing-index-candidates/README.md)
