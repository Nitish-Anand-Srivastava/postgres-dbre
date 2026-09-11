# Cardinality Estimation Errors

**Category:** Query Optimization | **Workflow:** `query-optimization/cardinality-estimation`

## 1. Problem Description

Almost every bad plan in PostgreSQL is a bad estimate wearing a costume. The planner chooses join strategies, join order, and access paths from its prediction of how many rows each node will produce; when that prediction is wrong by an order of magnitude, the resulting plan is wrong no matter how well the engine executes it. This workflow examines what the planner actually believes about an exchange's data -- distinct values, skew, null fractions, correlation, and the multi-column dependencies it cannot see by default -- and shows how to correct it.

## 2. Typical Symptoms

- An EXPLAIN ANALYZE plan where estimated rows and actual rows differ by one or more orders of magnitude at a specific node.
- A plan that flips between a nested loop and a hash join depending on the parameter values supplied.
- Query performance that is excellent for one market symbol or account and terrible for another, with identical query text.
- A query on a status or state column (order status, withdrawal state) whose plan assumes an even distribution that does not exist.

## 3. Business Impact

- An exchange's data is intensely skewed by nature: a handful of trading pairs carry most volume, most orders end in a small number of terminal states, and a few institutional accounts dwarf the rest. A planner that assumes uniformity is systematically wrong about exactly the queries that matter most.
- Estimation errors produce non-linear failures: the plan is fine until the data crosses a threshold, then collapses, which is why these incidents appear without any deployment to blame.
- Correcting an estimate is usually free and permanent (one ANALYZE, one statistics target change, one extended statistics object), making this among the highest-return investigations available.

## 4. Possible Root Causes

- Stale statistics: the last ANALYZE predates a bulk load, backfill, or a change in data distribution.
- Insufficient statistics resolution: default_statistics_target of 100 cannot describe a column with heavy skew and many distinct values, such as market symbol or account identifier.
- Correlated columns treated as independent: the planner multiplies the selectivity of market_symbol and order_status as if they were unrelated, when in reality certain statuses only occur for certain markets.
- Expressions and function calls in predicates, for which no statistics exist unless an expression index or extended statistics object provides them.
- A poor n_distinct estimate, which is sampled rather than exact and is frequently wrong for high-cardinality columns in very large tables.
- Join-key estimates across several joins compounding: a small error at the bottom of a deep join tree becomes an enormous one at the top.
- Partitioned tables where per-partition statistics exist but the query predicates prevent effective pruning, so estimates are drawn from the wrong scope.

## 5. Investigation Strategy

1. Start with statistics freshness -- a stale ANALYZE explains most estimation errors and is the cheapest thing to rule out.
2. Inspect what the planner actually stores for the suspect table's columns: distinct values, most common value frequencies, null fraction, and correlation.
3. Check the per-column statistics targets against the column's real distribution, since a skewed column may need far more than the default resolution.
4. Check whether extended statistics exist for the correlated column groups the queries filter on together.
5. Confirm the error empirically by comparing estimated and actual rows in a plan, under the guarded runbook.

## 6. Prerequisites

- Role membership in pg_monitor (or pg_read_all_stats), which grants the access needed to read pg_stats.
- The identity of the table and columns involved in the suspect predicate, set in the psql variables at the top of scripts 02 and 03.
- An understanding of the business meaning of the columns: knowing that order status and market symbol are correlated on an exchange is what turns a statistics reading into a diagnosis.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_statistics_freshness.sql`](scripts/01_statistics_freshness.sql) -- Ranks tables by how much they have changed since their last ANALYZE.
2. [`scripts/02_column_distribution_statistics.sql`](scripts/02_column_distribution_statistics.sql) -- Shows the planner's stored distribution statistics for every column of one table.
3. [`scripts/03_statistics_targets.sql`](scripts/03_statistics_targets.sql) -- Shows the per-column statistics target for one table alongside the cluster default.
4. [`scripts/04_extended_statistics_inventory.sql`](scripts/04_extended_statistics_inventory.sql) -- Lists the extended statistics objects defined in this database and the columns they cover.
5. [`scripts/05_confirm_estimate_error.md`](scripts/05_confirm_estimate_error.md) -- Guarded runbook for measuring estimated versus actual rows and applying the correct statistics remediation.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Statistics live in the shared cluster storage as ordinary catalog data, so an ANALYZE run on the writer immediately benefits every reader in the cluster -- there is no need to analyze per instance.
- default_statistics_target is set through the Aurora DB cluster parameter group; per-column targets are set with ALTER TABLE and are usually the better-targeted choice.
- An Aurora failover does not lose planner statistics (they are catalog data, not in-memory counters), unlike pg_stat_statements, which does not survive it.

## 8. Interpretation Guide

- n_distinct is a sampled estimate, not a count. A positive value is an absolute number of distinct values; a negative value between -1 and 0 is a ratio of distinct values to total rows (-1 means every row is unique). A value that badly misdescribes reality on a large table is a strong candidate for an explicit override.
- most_common_value_frequency shows how dominant the single most frequent value is. On an exchange this is where skew becomes visible: if one market symbol is 40% of the rows, the planner knows that only if that value is captured in the most common value list.
- mcv_entries is bounded by the column's statistics target. A column with 5,000 distinct values and a target of 100 keeps only the top 100, so the frequencies of everything else are approximated from the remaining histogram -- which is exactly where estimates for mid-frequency values go wrong.
- null_frac matters more than it appears: a column that is 95% NULL (for example settled_at on open orders) makes IS NULL and IS NOT NULL predicates wildly different in selectivity, and a planner without that information will misjudge both.
- correlation near zero makes ordered index scans look expensive; near 1 or -1 makes them look cheap. It is a physical-layout statistic and changes after a table rewrite or repack.
- Extended statistics (CREATE STATISTICS) are the only mechanism that teaches the planner about dependencies between columns. Without them, the estimate for a two-column predicate is the product of two independent selectivities, which for correlated exchange columns is wrong by orders of magnitude in the safe direction (too small) -- which is precisely what produces runaway nested loops.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Run a targeted ANALYZE on the implicated table if its statistics are stale; this frequently corrects the estimate and the plan within seconds (see stale-statistics for the guarded runbook).

**Short-term remediation** (hours to days):

- Raise the statistics target for the specific skewed column and re-analyze, rather than raising default_statistics_target cluster-wide.
- Create extended statistics for the correlated column groups the application filters on together, then ANALYZE the table so they are populated.
- Add an expression index where a predicate wraps a column in a function, which both enables index use and provides statistics for the expression.

**Long-term engineering fix** (days to weeks):

- Add statistics-target and extended-statistics decisions to the schema definition for hot exchange tables, so they survive table rebuilds and environment recreation instead of being re-discovered during incidents.
- Include representative production-scale data in pre-production so plan differences driven by skew are caught before release.
- Review the autoanalyze scale factor for very large tables, where the default 10% threshold means an enormous absolute number of modifications before statistics are refreshed.

## 10. Production Safety

- All .sql scripts here are read-only catalog and statistics reads.
- Comparing estimates against actuals requires executing the query, which is why it is a guarded runbook. Deciding to actually execute a candidate production query is an operator judgement call, not something an investigation script may do on the operator's behalf. That is why every EXPLAIN ANALYZE step in this toolkit is a markdown runbook rather than a .sql file.
- ANALYZE and CREATE STATISTICS are not run by any script in this workflow: they are change-managed actions documented in the runbook, because ANALYZE on a very large table consumes I/O and CREATE STATISTICS is a schema change.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Statistics are fresh, targets are adequate, extended statistics exist, and the estimate is still wrong by orders of magnitude -- this is a genuinely hard estimation case that needs engineering input on query shape.
- The estimation error affects a settlement, reconciliation, or compliance query with a deadline.
- Correcting the estimate requires an ANALYZE on a table large enough that its I/O cost needs a maintenance window.

## 12. Related Issues

- [stale-statistics](../stale-statistics/README.md)
- [analyze-query-plan](../analyze-query-plan/README.md)
- [nested-loop-problems](../nested-loop-problems/README.md)
- [query-plan-regression](../query-plan-regression/README.md)
- [analyze-statistics](../../vacuum-and-autovacuum/analyze-statistics/README.md)
