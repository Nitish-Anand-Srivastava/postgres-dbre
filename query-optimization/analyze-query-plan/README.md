# Analyze a Query Plan

**Category:** Query Optimization | **Workflow:** `query-optimization/analyze-query-plan`

## 1. Problem Description

The structured method for taking a specific slow statement on an Aurora PostgreSQL 17 exchange database and understanding why the planner chose the plan it did. It starts from evidence that costs nothing (pg_stat_statements aggregates, table and index statistics, planner configuration), and only then decides whether capturing a real execution profile is justified -- because EXPLAIN is free and EXPLAIN ANALYZE actually runs the statement, with every consequence that implies on a production order book.

## 2. Typical Symptoms

- A specific statement has been identified as slow by pg_stat_statements, by application tracing, or by a user-visible latency complaint on order placement, balance lookup, or trade history.
- A query performs acceptably in staging against a small dataset and unacceptably in production against hundreds of millions of rows.
- Latency for one statement is bimodal: usually fast, occasionally many times slower, suggesting more than one plan or a parameter-dependent plan choice.

## 3. Business Impact

- A single badly planned statement on the order-placement or balance-check path multiplies across the exchange's request rate: at thousands of requests per second, an extra 50ms per call is a queue that never drains during a volatility spike.
- Plan problems tend to be non-linear: a nested loop that is fine at 10,000 rows becomes catastrophic at 10 million, so a query that has been healthy for a year can fail abruptly as a table crosses a threshold.
- Reading plans correctly is what separates a targeted 20-minute fix (one index, one ANALYZE, one rewritten predicate) from a speculative multi-day optimization effort.

## 4. Possible Root Causes

- Estimation error: the planner's row estimate for a node is far from reality, so it chooses a join strategy that would have been correct for the estimated size.
- Stale or insufficient statistics: last ANALYZE predates a bulk load, or default_statistics_target is too low for a skewed column such as market symbol or order status.
- Missing or unusable index: no index supports the predicate, or an index exists but the predicate is not sargable (a function or type cast wrapped around the indexed column).
- Correlated predicates the planner treats as independent, producing an estimate that is the product of two selectivities when the real selectivity is far higher -- the classic case for extended statistics.
- Configuration that misrepresents the hardware: random_page_cost and effective_cache_size left at defaults that do not describe Aurora's distributed storage and the instance's real cache size.
- Parameter-sensitive plans: a generic plan cached for a prepared statement that is good for typical parameters and terrible for outliers (one enormous account, one extremely liquid trading pair).

## 5. Investigation Strategy

1. Identify the statement objectively from pg_stat_statements, ranked by total time, so effort goes where the database actually spends it.
2. Check mean and maximum execution time for that statement to distinguish 'always slow' from 'occasionally catastrophic'.
3. If planning time is being tracked, check whether time is going into planning rather than execution.
4. Review the planner configuration that shaped the decision.
5. Inspect the tables and indexes the statement touches: sizes, index definitions, usage counters, and statistics freshness.
6. Only then decide how to capture a plan: EXPLAIN first (free, no execution), and EXPLAIN ANALYZE only under the guardrails in the runbook.

## 6. Prerequisites

- Role membership in pg_monitor (or pg_read_all_stats).
- pg_stat_statements installed, ideally with pg_stat_statements.track_planning enabled if planning time is in question (it is off by default because it adds overhead).
- The statement text or queryid under investigation, plus realistic parameter values for it -- a plan captured with unrepresentative parameters answers the wrong question.
- Awareness of which tables the statement touches, so the table-level steps can be pointed at them.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_identify_statement_by_total_time.sql`](scripts/01_identify_statement_by_total_time.sql) -- Ranks statements by cumulative execution time so plan analysis effort is spent where the database actually spends its time.
2. [`scripts/02_statement_latency_profile.sql`](scripts/02_statement_latency_profile.sql) -- Shows mean, standard deviation, and maximum execution time per statement to separate consistently slow from occasionally catastrophic.
3. [`scripts/03_planning_vs_execution_time.sql`](scripts/03_planning_vs_execution_time.sql) -- Separates time spent planning from time spent executing, to detect planning-bound statements.
4. [`scripts/04_planner_configuration.sql`](scripts/04_planner_configuration.sql) -- Snapshots the planner and executor configuration that shaped the plan choice.
5. [`scripts/05_target_table_indexes_and_statistics.sql`](scripts/05_target_table_indexes_and_statistics.sql) -- Inventories the indexes and statistics freshness of the table the statement touches.
6. [`scripts/06_capture_plan_safely.md`](scripts/06_capture_plan_safely.md) -- Guarded runbook for capturing a query plan: EXPLAIN first, EXPLAIN ANALYZE only under explicit production guardrails.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Aurora's storage layer is network-attached and shared, so a shared buffer miss costs a network round trip. random_page_cost left at the community default of 4.0 often overstates the penalty for random access relative to Aurora's actual behavior, and effective_cache_size left low understates how much data is effectively cached -- both push the planner toward sequential scans it should not choose.
- Aurora does not support ALTER SYSTEM for planner parameters. Persistent changes go through the DB cluster or DB instance parameter group; per-session experiments use SET or SET LOCAL and affect only that session.
- Readers are the right place to capture an execution profile for a read-only statement: they carry a copy of the same data, and a heavy EXPLAIN ANALYZE there does not compete with order matching on the writer. Be aware their cache contents differ from the writer's, so buffer hit ratios in the plan will not match exactly.
- pg_stat_statements counters live in instance memory and are reset by an Aurora failover, so a statement's history disappears when the writer changes. Persist the output if it is needed as a baseline.

## 8. Interpretation Guide

- EXPLAIN shows the plan the planner would choose and its cost estimates. It does not execute the statement, takes no row locks, is safe against SELECT and against INSERT/UPDATE/DELETE alike, and should always be the first capture.
- EXPLAIN ANALYZE executes the statement for real. For a SELECT that means consuming the same I/O, CPU, memory, and time as the original slow query; for a data-modifying statement it means actually performing the writes unless it is wrapped in a transaction that is rolled back.
- Cost units are not milliseconds. Compare costs between alternative plans for the same query, never across different queries, and never treat a cost number as a time prediction.
- The single most informative signal in an EXPLAIN ANALYZE plan is the ratio of estimated rows to actual rows at each node. Find the deepest node where they diverge by an order of magnitude: that is where the planner was misled, and everything above it is a consequence rather than a cause.
- For nodes inside a loop, actual rows is reported per loop: multiply by the loops value to get the true total, which is exactly where a nested loop's real cost hides.
- PostgreSQL 17 adds EXPLAIN (ANALYZE, SERIALIZE), which measures the time spent converting result rows into wire format. Use it when a query returns a very large result set and the plan itself looks reasonable -- the cost may be in serialization and transfer rather than in the plan.
- On Aurora, a buffer miss is a read from the distributed storage layer rather than a local disk read, so the BUFFERS output (shared read versus shared hit) maps more directly to latency than it does on a self-managed server with a local page cache.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If a single statement is actively harming the platform, apply the narrowest safe mitigation first: cancel or rate-limit the offending workload, or have the application stop issuing it, while the real fix is prepared.
- If the cause is clearly stale statistics, run a targeted ANALYZE on the implicated table as a change-managed action (see stale-statistics for the guarded runbook).

**Short-term remediation** (hours to days):

- Add the specific missing index identified by the plan, built with CREATE INDEX CONCURRENTLY so the exchange's write path is not blocked.
- Rewrite a non-sargable predicate (a function or cast applied to the indexed column) so an existing index can be used, or add a matching expression index.
- Raise the statistics target on a badly estimated skewed column, or create extended statistics for correlated predicate pairs, then re-analyze.

**Long-term engineering fix** (days to weeks):

- Capture and store plan baselines for the exchange's critical statements so a future regression is detected by comparison rather than by a user complaint.
- Tune random_page_cost and effective_cache_size to describe the actual Aurora instance rather than the 1990s-era defaults, cluster-wide, under change management.
- Partition the very large tables whose scan sizes drive these plan problems, so partition pruning reduces the planner's work rather than requiring ever more index tuning.

## 10. Production Safety

- Every .sql script in this workflow is read-only: statistics views, catalogs, and configuration only. None of them executes the statement under investigation.
- The EXPLAIN and EXPLAIN ANALYZE guidance is deliberately a markdown runbook, not an executable script, because running the candidate statement is a decision that requires an operator to weigh production impact. Deciding to actually execute a candidate production query is an operator judgement call, not something an investigation script may do on the operator's behalf. That is why every EXPLAIN ANALYZE step in this toolkit is a markdown runbook rather than a .sql file.
- Never run EXPLAIN ANALYZE on a data-modifying statement outside an explicit transaction you intend to roll back, and never run it at all against a statement whose full execution you are not prepared to complete.
- Prefer capturing an execution profile on a reader instance when the statement is a read, so the writer's order-matching path is unaffected.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- The plan is understood but the fix requires a schema change to a hot exchange table (a new index on orders, ledger_entries, or wallets) -- escalate to schema-changes for a safe rollout plan.
- The statement cannot be made acceptably fast without an application-side change to its shape, pagination, or caching strategy.
- The plan is correct and the statement is simply doing too much work for the data volume -- escalate to a partitioning or archival conversation rather than continuing to tune.
- A plan regression is suspected rather than a persistently bad plan -- switch to the query-plan-regression workflow, which is built around before/after comparison.

## 12. Related Issues

- [cardinality-estimation](../cardinality-estimation/README.md)
- [stale-statistics](../stale-statistics/README.md)
- [nested-loop-problems](../nested-loop-problems/README.md)
- [query-plan-regression](../query-plan-regression/README.md)
- [inefficient-index-usage](../inefficient-index-usage/README.md)
- [slow-queries](../../performance/slow-queries/README.md)
- [missing-index-candidates](../../tables-and-indexes/missing-index-candidates/README.md)
