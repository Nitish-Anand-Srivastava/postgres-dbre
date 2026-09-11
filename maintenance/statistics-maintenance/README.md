# Planner Statistics Maintenance

**Category:** Maintenance | **Workflow:** `maintenance/statistics-maintenance`

## 1. Problem Description

The standing maintenance workflow for planner statistics: which tables are drifting away from their last ANALYZE, whether per-table autovacuum/analyze settings are tuned for the tables that actually need it, and whether columns on the hot trading paths need a raised statistics target or an extended (multi-column) statistics object. This is the preventive counterpart to the reactive stale-statistics investigation in query-optimization.

## 2. Typical Symptoms

- Plans flip between good and bad for the same query shape with no code change, typically after a large batch load into an orders, trades, or ledger table.
- The routine maintenance checklist keeps flagging the same tables as having a large n_mod_since_analyze relative to their row count.
- The planner's row estimates are wildly wrong for queries filtering on two correlated columns (for example, market symbol and side, or currency and account type).

## 3. Business Impact

- Stale statistics on the order-matching and balance-lookup paths produce plans that are orders of magnitude slower than the correct plan -- the same query that normally serves an order book in milliseconds can start sequentially scanning a multi-hundred-million-row trades table during peak volatility.
- Statistics problems are the cheapest class of performance problem to prevent and one of the most expensive to diagnose during a live incident, because the query text and the schema both look unchanged.
- Correlated-column misestimates on compliance and reporting queries cause them to overrun their windows, delaying regulatory reporting.

## 4. Possible Root Causes

- Default autovacuum_analyze_scale_factor (0.1) means a very large table must accumulate 10% modified rows before autoanalyze triggers -- on a 500 million row trades table that is 50 million rows of drift, which is far too much for time-series-skewed data.
- Bulk loads and large archival deletes change a table's distribution far faster than autoanalyze reacts, leaving a window where plans are chosen from a distribution that no longer exists.
- The default statistics target (100) is too coarse for highly skewed columns -- a handful of dominant trading pairs plus a long tail of thin markets is exactly the distribution that a small histogram represents badly.
- PostgreSQL assumes column independence without an extended statistics object, so correlated predicates multiply selectivities and produce estimates far below reality.
- Per-table storage parameters set years ago for a table that has since grown by two orders of magnitude are no longer appropriate but nobody revisits them.

## 5. Investigation Strategy

1. Rank tables by how far they have drifted since their last analyze, weighted by how large and how hot they are.
2. Check which tables already carry per-table autovacuum/analyze storage parameter overrides, and whether those overrides still match the table's current size and churn.
3. Check for non-default per-column statistics targets and for existing extended statistics objects, so tuning builds on what is there rather than duplicating it.
4. Tie each finding to a specific query or plan problem where possible -- raising a statistics target everywhere costs planning time on every query, so it should be targeted.

## 6. Prerequisites

- pg_monitor role membership for the read-only scripts; table ownership (or pg_maintain membership) to apply any ANALYZE, statistics target change, or extended statistics object.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_statistics_drift_ranking.sql`](scripts/01_statistics_drift_ranking.sql) -- Ranks tables by how far their contents have drifted since the last ANALYZE, which is the primary input to every other decision in this workflow.
2. [`scripts/02_per_table_autovacuum_and_analyze_settings.sql`](scripts/02_per_table_autovacuum_and_analyze_settings.sql) -- Shows which tables already carry per-table autovacuum/analyze storage parameter overrides, alongside their current size and churn, so tuning decisions build on what is already configured.
3. [`scripts/03_column_targets_and_extended_statistics.sql`](scripts/03_column_targets_and_extended_statistics.sql) -- Lists non-default per-column statistics targets and every extended (multi-column) statistics object, so correlated-column tuning is visible and not duplicated.
4. [`scripts/04_statistics_maintenance_runbook.md`](scripts/04_statistics_maintenance_runbook.md) -- Guarded runbook for applying the statistics maintenance actions this workflow identifies: targeted ANALYZE, per-table thresholds, statistics targets, and extended statistics.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Autovacuum and autoanalyze thresholds on Aurora are controlled through the DB cluster parameter group rather than postgresql.conf (see maintenance/parameter-group-change-management), but per-table storage parameter overrides are ordinary PostgreSQL DDL and work exactly as they do in community PostgreSQL -- which makes per-table overrides the more precise tool for a handful of very large tables, since they need no parameter-group change or reboot.

## 8. Interpretation Guide

- n_mod_since_analyze compared against the table's live row count is the real drift signal; a raw modification count is meaningless without that ratio. A 2% drift on a 500 million row table can matter more than a 50% drift on a 10,000 row lookup table, because the absolute number of rows the planner is now wrong about is far larger.
- last_autoanalyze being NULL on a large, actively written table is a strong signal that autoanalyze has never successfully completed there -- check autovacuum worker saturation (vacuum-and-autovacuum/autovacuum-not-keeping-up) rather than assuming the thresholds are the problem.
- A per-table override that sets autovacuum_analyze_scale_factor to a small value (0.01 or lower) on a huge table is usually correct and deliberate; the same override on a small table just burns autovacuum worker cycles for no benefit.
- An existing extended statistics object only helps if it has actually been analyzed -- creating it is not enough, the next ANALYZE on the table is what populates it.
- Raising a column's statistics target increases both ANALYZE cost and per-query planning time. Target it at the specific skewed columns real plans are getting wrong, not at every column on the table.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If a plan regression is live right now, a targeted ANALYZE of the affected table is the fastest safe corrective action -- see query-optimization/stale-statistics for the incident path; this workflow is about not getting there again.

**Short-term remediation** (hours to days):

- Run a targeted ANALYZE on the drifted tables identified by script 01, and set per-table autovacuum_analyze_scale_factor overrides on the largest, highest-churn tables so autoanalyze triggers on a sensible absolute row count rather than a percentage of an enormous table.

**Long-term engineering fix** (days to weeks):

- Make a post-bulk-load ANALYZE a mandatory step in every batch/ETL and archival job rather than leaving the refresh to autoanalyze's schedule.
- Add extended statistics objects for the correlated column pairs that recur in the platform's hot query shapes, and review them whenever those query shapes change.
- Re-review per-table statistics settings whenever a table crosses an order-of-magnitude growth boundary, as part of the routine maintenance checklist.

## 10. Production Safety

- Every SQL script in this workflow is strictly read-only.
- ANALYZE takes a SHARE UPDATE EXCLUSIVE lock: ordinary reads and writes continue, but it conflicts with other maintenance operations (VACUUM, another ANALYZE, DDL) on the same table, and it is real I/O on a large table.
- Setting a statistics target or creating an extended statistics object is DDL requiring a brief ACCESS EXCLUSIVE (SHARE UPDATE EXCLUSIVE for CREATE STATISTICS) lock, and neither takes effect until the next ANALYZE of the table.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- A table shows extreme drift and its last_autoanalyze is NULL or very old despite autovacuum being enabled -- this is an autovacuum capacity problem, not a statistics problem, and belongs with vacuum-and-autovacuum/autovacuum-not-keeping-up.
- A plan regression persists on the hot trading path immediately after a successful targeted ANALYZE -- statistics are not the cause; escalate to query-optimization/query-regression.

## 12. Related Issues

- [routine-maintenance-checklist](../routine-maintenance-checklist/README.md)
- [minor-version-upgrade-readiness](../minor-version-upgrade-readiness/README.md)
- [table-bloat](../../vacuum-and-autovacuum/table-bloat/README.md)
- [large-tables](../../tables-and-indexes/large-tables/README.md)
- [comprehensive-health-check](../../database-health/comprehensive-health-check/README.md)
