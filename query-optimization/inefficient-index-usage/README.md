# Inefficient Index Usage

**Category:** Query Optimization | **Workflow:** `query-optimization/inefficient-index-usage`

## 1. Problem Description

An index can be present, valid, and still be the wrong answer: the planner may ignore it, it may be scanned but discard most of what it reads, it may duplicate another index, or it may never have been used at all while still taxing every insert on the order path. This workflow separates those cases using the catalog and the index statistics, so index changes on an exchange's hot tables are made from evidence rather than from intuition.

## 2. Typical Symptoms

- A query performs a sequential scan on a large table that visibly has a relevant index.
- Index scans return far more tuples than the query ultimately uses, indicating a poorly matched index.
- Write latency on orders, trades, or ledger_entries has grown as indexes accumulated over time.
- Index storage is a large fraction of total table storage on the biggest tables.

## 3. Business Impact

- Every index is write amplification: each insert into trades or ledger_entries must update every index on that table, so unused indexes tax the exchange's most latency-critical path continuously and invisibly.
- An index the planner refuses to use gives the worst of both outcomes -- full write and storage cost, zero read benefit.
- Index bloat and duplication inflate storage on the Aurora cluster volume, which never shrinks once grown.

## 4. Possible Root Causes

- Predicate not sargable: a function or cast wrapped around the indexed column, so the index cannot be matched.
- Type or collation mismatch between the column and the comparison value, preventing index use.
- Wrong leading column: an index on (created_at, account_id) cannot serve a lookup on account_id alone.
- Low selectivity: the planner correctly judges that a sequential scan is cheaper than an index scan returning a large fraction of the table.
- Stale statistics making the index look less selective than it is.
- Duplicate or redundant indexes accumulated over years of incremental change, where one is a prefix of another.
- Indexes created for a feature or report that no longer exists, never removed.
- random_page_cost and effective_cache_size describing hardware that is not this Aurora instance, systematically biasing the planner against index scans.

## 5. Investigation Strategy

1. Inventory index size and scan activity across the database to see where index effort and index cost actually are.
2. Identify indexes with no recorded scans, being careful about the reset semantics of those counters.
3. Identify structurally duplicate indexes, which are pure overhead by definition.
4. Measure index scan efficiency: how many tuples each scan reads versus how many it returns.
5. Cross-check tables where sequential scans dominate despite indexes existing.
6. Validate any proposed index change safely before applying it to a hot table.

## 6. Prerequisites

- Role membership in pg_monitor (or pg_read_all_stats).
- Knowledge of when statistics were last reset -- idx_scan restarts at zero on instance restart, on failover, and on pg_stat_reset(), and acting on a reset counter is how correct indexes get dropped.
- The business cycle context: month-end reconciliation, quarterly regulatory reporting, and audit queries can leave an index unused for weeks and then make it essential.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_index_inventory_and_usage.sql`](scripts/01_index_inventory_and_usage.sql) -- Inventories every index with its size and scan activity, including the last-used timestamp.
2. [`scripts/02_unused_index_candidates.sql`](scripts/02_unused_index_candidates.sql) -- Lists indexes with no recorded scans, excluding those backing constraints.
3. [`scripts/03_duplicate_indexes.sql`](scripts/03_duplicate_indexes.sql) -- Finds structurally duplicate indexes on the same table.
4. [`scripts/04_index_scan_efficiency.sql`](scripts/04_index_scan_efficiency.sql) -- Measures how many tuples each index scan reads versus how many the executor actually keeps.
5. [`scripts/05_sequential_scan_cross_check.sql`](scripts/05_sequential_scan_cross_check.sql) -- Cross-checks tables where sequential scans dominate despite indexes being present.
6. [`scripts/06_validate_index_change_safely.md`](scripts/06_validate_index_change_safely.md) -- Guarded runbook for validating an index addition or removal before applying it to a hot exchange table.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Index statistics are per-instance in-memory counters. The writer and each reader maintain their own, and all of them reset on restart or failover -- so a complete picture requires querying every instance in the cluster, not just the writer.
- Building an index consumes cluster volume that is not returned when another index is dropped: Aurora storage keeps its high-water mark, so removing an unused index frees space for reuse inside the database but does not reduce the storage bill.
- Aurora's network-attached storage changes the relative cost of random versus sequential access, so leaving random_page_cost at the community default of 4.0 biases the planner toward sequential scans more than the hardware justifies.

## 8. Interpretation Guide

- idx_scan of zero means 'not used since the counters were reset', never 'not needed'. On an Aurora cluster that has failed over recently, every counter may be hours old. Check instance uptime and stats_reset before drawing any conclusion.
- PostgreSQL 16 and later also record last_idx_scan, a timestamp. It is far more trustworthy than the counter, because it survives as a statement about when the index was genuinely last useful.
- A large gap between idx_tup_read and idx_tup_fetch means the index scan reads many entries and the executor discards most of them -- typically a poorly ordered composite index, or one missing a column needed by the filter.
- Index counters on a reader reflect only that reader's own workload. An index unused on the writer may be heavily used by reporting on a reader, so check every instance before concluding anything.
- Indexes backing primary keys, unique constraints, and exclusion constraints exist for correctness, not performance. They must never be dropped on usage evidence.
- An index that is a strict leading-column prefix of another (a on (a) versus (a, b)) is usually redundant, but not always: a narrower index is smaller, fits in cache better, and can be meaningfully faster for a very hot lookup. Judge each case rather than applying the rule mechanically.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- None. Index changes on exchange tables are planned changes, not incident responses -- the only exception is rebuilding an index that is actually invalid.

**Short-term remediation** (hours to days):

- Rewrite non-sargable predicates, or add the matching expression index, so an existing index becomes usable.
- Add the correctly ordered composite index the workload actually needs, built CONCURRENTLY.
- Run a targeted ANALYZE where stale statistics are making the planner misjudge index selectivity.

**Long-term engineering fix** (days to weeks):

- Establish a periodic index review covering a full business cycle, so unused and duplicate indexes are removed deliberately rather than discovered during a storage incident.
- Treat index additions as schema changes with a stated query they serve, so indexes cannot accumulate anonymously.
- Tune random_page_cost and effective_cache_size to describe the actual Aurora instance, so the planner stops systematically preferring sequential scans.

## 10. Production Safety

- All .sql scripts here are read-only catalog and statistics reads; none of them creates or drops anything.
- Any index change is a schema change: build with CREATE INDEX CONCURRENTLY and drop with DROP INDEX CONCURRENTLY, because the non-concurrent forms take locks that block all traffic to the table for the duration.
- Never drop an index on the evidence of a single reading. Confirm across at least one full business cycle and across every instance in the cluster, and keep the exact index definition so it can be recreated quickly if the decision proves wrong.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- A proposed index change affects orders, trades, wallets, or ledger_entries -- escalate for review, because the write-path impact is felt by every trade.
- An index appears unused on the writer but the reporting team cannot confirm it is unused on the readers.
- Index storage growth is a material component of the cluster's storage trend -- escalate into the capacity conversation rather than handling it as a local tuning task.

## 12. Related Issues

- [analyze-query-plan](../analyze-query-plan/README.md)
- [cardinality-estimation](../cardinality-estimation/README.md)
- [merge-join-analysis](../merge-join-analysis/README.md)
- [unused-indexes](../../tables-and-indexes/unused-indexes/README.md)
- [duplicate-indexes](../../tables-and-indexes/duplicate-indexes/README.md)
- [missing-index-candidates](../../tables-and-indexes/missing-index-candidates/README.md)
- [sequential-scan-investigation](../../tables-and-indexes/sequential-scan-investigation/README.md)
