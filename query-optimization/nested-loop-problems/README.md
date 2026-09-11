# Nested Loop Join Problems

**Category:** Query Optimization | **Workflow:** `query-optimization/nested-loop-problems`

## 1. Problem Description

A nested loop join re-executes the inner side once per outer row. That is the fastest possible strategy when the outer side really does produce a handful of rows and the inner side has a supporting index -- and it is the single most destructive plan shape in PostgreSQL when the planner underestimates the outer row count. This workflow finds statements whose block-access-per-row profile is characteristic of a runaway nested loop, identifies the estimation error or missing index behind it, and guards the decision to confirm it with a real execution profile.

## 2. Typical Symptoms

- A statement's execution time scales super-linearly with data growth: fine last quarter, unusable now, with no code change in between.
- Very high shared block reads per row returned -- the query touches far more of the database than the size of its result justifies.
- A join between a filtered table and a large table (trades, ledger_entries, order_fills) that is fast for narrow filters and pathological for wide ones.
- An EXPLAIN ANALYZE plan showing a Nested Loop whose inner node has a large loops count, where actual rows multiplied by loops is orders of magnitude above the estimate.

## 3. Business Impact

- A runaway nested loop consumes CPU and storage I/O out of all proportion to the work it accomplishes, so a single such statement can saturate an instance and degrade every unrelated query on the exchange at the same time.
- The failure is abrupt rather than gradual: the plan stays reasonable until the outer row count crosses a threshold, then collapses, which makes it a common cause of 'nothing changed but everything is slow' incidents.
- Because it commonly appears on reporting, reconciliation, and compliance-export queries joining trades to accounts to ledger entries, it tends to fire at month end -- exactly when those reports are time-critical.

## 4. Possible Root Causes

- Cardinality underestimation on the outer side: the planner expects a few rows, chooses a nested loop, and then executes the inner side millions of times.
- Stale statistics after a bulk load or backfill, so the planner's row estimates describe a table that no longer exists.
- A missing index on the inner side's join key, turning each of the millions of inner executions into a sequential scan.
- Correlated predicates treated as independent (for example market symbol and order status, which are strongly correlated on an exchange), multiplying selectivities and producing an estimate far below reality.
- A join key whose type differs between the two tables, preventing index use on the inner side even though an index exists.
- A LIMIT clause that makes a nested loop look cheap to the planner because it expects to stop early, when in practice the filter matches nothing until very late in the scan.

## 5. Investigation Strategy

1. Find statements with an extreme ratio of blocks accessed to rows returned -- the fingerprint of repeated inner-side execution.
2. Check which tables are being scanned sequentially in bulk, since an unindexed inner side turns into a scan per outer row.
3. Check for foreign keys without a supporting index, the most common structural cause of an unindexed inner side in a normalized exchange schema.
4. Check statistics freshness on the tables involved, because underestimation is usually a statistics problem rather than a planner defect.
5. Review the planner settings that influence the nested loop choice, including enable_memoize, which materially changes how expensive repeated inner lookups are.
6. Only then capture a plan, following the guarded runbook, to confirm the nested loop and measure the true loop count.

## 6. Prerequisites

- Role membership in pg_monitor (or pg_read_all_stats).
- pg_stat_statements for the statement-level steps (the scripts degrade gracefully to a notice without it).
- The identity of the statement or report under investigation, and the tables it joins.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_high_block_access_per_row.sql`](scripts/01_high_block_access_per_row.sql) -- Finds statements that touch a disproportionate number of blocks for the number of rows they return.
2. [`scripts/02_sequential_scan_pressure.sql`](scripts/02_sequential_scan_pressure.sql) -- Identifies tables being read sequentially in bulk, the signature of an unindexed inner side.
3. [`scripts/03_foreign_keys_missing_index.sql`](scripts/03_foreign_keys_missing_index.sql) -- Finds foreign key constraints with no supporting index on the referencing side.
4. [`scripts/04_statistics_freshness.sql`](scripts/04_statistics_freshness.sql) -- Checks whether the planner's row estimates for the joined tables are based on current data.
5. [`scripts/05_join_strategy_settings.sql`](scripts/05_join_strategy_settings.sql) -- Reviews the planner settings that govern join strategy selection and repeated-lookup caching.
6. [`scripts/06_confirm_nested_loop_safely.md`](scripts/06_confirm_nested_loop_safely.md) -- Guarded runbook for confirming a runaway nested loop with a real plan, and for testing the alternative plan safely.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Each inner-side lookup that misses shared buffers becomes a read from Aurora's distributed storage, so the cost of a runaway loop is amplified relative to a server with local disks: millions of small random reads is the worst possible access pattern for network-attached storage.
- Aurora readers can be used to reproduce and confirm the plan for a read-only statement without adding load to the writer, but their buffer cache contents differ, so absolute buffer numbers will not match the writer's.
- effective_cache_size on Aurora should reflect the instance's real memory rather than the community default; when it is too low the planner underestimates how much of the inner side is cached and its nested-loop costing is distorted.

## 8. Interpretation Guide

- Blocks accessed per row returned is the key derived metric: a statement returning 50 rows while touching two million blocks is re-scanning something, and a nested loop is the most likely reason.
- A nested loop is not intrinsically wrong. With a small outer side and an indexed inner side it is the optimal join for most OLTP lookups on an exchange -- the goal is to find the ones where the outer estimate was wrong, not to eliminate the plan shape.
- PostgreSQL 14 and later can place a Memoize node above the inner side, caching results for repeated parameter values. It softens the damage when inner keys repeat, and does nothing when they are distinct -- so a plan with Memoize can still be a runaway loop.
- If the estimate is right and the loop count is genuinely large, the fix is a different join strategy (usually a hash join), which is normally achieved by fixing statistics or adding an index rather than by disabling the plan type.
- Never fix this by turning off enable_nestloop in production. It is a diagnostic tool: setting it off for a single session proves the alternative plan is better, but leaving it off distorts every other query on the connection.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Stop the bleeding first if a runaway statement is currently saturating the instance: have the application stop issuing it, or cancel the specific backend under the concurrency-and-locking runbook.
- If statistics are clearly stale on a joined table, a targeted ANALYZE frequently restores a sane plan within seconds (run it as a change-managed action -- see stale-statistics).

**Short-term remediation** (hours to days):

- Add the missing index on the inner side's join key, built with CREATE INDEX CONCURRENTLY.
- Add extended statistics for correlated predicate pairs so the outer-side estimate stops being the product of two independent selectivities.
- Raise the statistics target on the skewed column driving the underestimate, then re-analyze that table.
- Fix join-key type mismatches in the schema or the query so the inner index becomes usable at all.

**Long-term engineering fix** (days to weeks):

- Rewrite or decompose the reporting and reconciliation queries that repeatedly produce this shape, for example by materializing an intermediate aggregate rather than joining raw trades to raw ledger entries.
- Partition the large inner-side tables so that even a badly chosen loop touches only the relevant partitions.
- Add plan-shape regression testing against production-scale data for the exchange's critical reports, so an estimation-driven collapse is caught before release.

## 10. Production Safety

- All .sql scripts here are read-only aggregate and catalog queries; none executes the statement under investigation.
- Confirming a nested loop with EXPLAIN ANALYZE means executing the runaway statement in full, which is exactly the thing causing the incident -- that is why it is a guarded runbook with an explicit statement_timeout requirement. Deciding to actually execute a candidate production query is an operator judgement call, not something an investigation script may do on the operator's behalf. That is why every EXPLAIN ANALYZE step in this toolkit is a markdown runbook rather than a .sql file.
- Never disable enable_nestloop cluster-wide as a remediation; if it is used at all, it is used with SET LOCAL inside a single diagnostic session.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- A runaway nested loop is currently saturating the writer and the owning team cannot stop issuing the statement -- escalate as an active incident.
- The fix requires a new index on a hot exchange table -- escalate to schema-changes for a safe concurrent rollout.
- Correct statistics and correct indexes still produce the loop, meaning the query shape itself must change -- escalate to the application team with the plan evidence.

## 12. Related Issues

- [analyze-query-plan](../analyze-query-plan/README.md)
- [cardinality-estimation](../cardinality-estimation/README.md)
- [stale-statistics](../stale-statistics/README.md)
- [hash-join-analysis](../hash-join-analysis/README.md)
- [inefficient-index-usage](../inefficient-index-usage/README.md)
- [missing-index-candidates](../../tables-and-indexes/missing-index-candidates/README.md)
- [slow-queries](../../performance/slow-queries/README.md)
