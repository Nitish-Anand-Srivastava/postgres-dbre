# Merge Join Analysis

**Category:** Query Optimization | **Workflow:** `query-optimization/merge-join-analysis`

## 1. Problem Description

A merge join walks two inputs in sorted order simultaneously. When both inputs already arrive sorted -- typically from an index scan on the join key -- it is extremely efficient and memory-light, which makes it the ideal strategy for large time-ordered joins such as trades to fills or ledger entries to settlement batches. When the inputs are not already sorted, PostgreSQL must sort them first, and those sorts can spill to disk and dominate the query's cost. This workflow determines which situation you are in and what to do about it.

## 2. Typical Symptoms

- A large join whose cost is dominated by explicit Sort nodes rather than by the join itself.
- Temporary file usage attributable to sorts feeding a join rather than to a user-visible ORDER BY.
- A time-range join over trades or ledger entries that performs far worse than its row counts suggest it should.
- A plan that alternates between merge join and hash join across executions or environments, with markedly different performance.

## 3. Business Impact

- Reconciliation and settlement jobs joining large time-ordered datasets are exactly the workload where a merge join should excel; when it degenerates into sort-then-merge with spills, those jobs miss their processing windows.
- Sorts feeding a merge join consume work_mem per node and spill to local instance storage, so several concurrent such jobs can exhaust temporary space and cause unrelated failures.
- The fix is often a single well-chosen index that makes both sides arrive pre-sorted, converting a multi-minute batch job into a streaming one -- high leverage, low risk.

## 4. Possible Root Causes

- No index providing sorted input on the join key, so both sides must be explicitly sorted first.
- An index exists but its sort order (ASC/DESC, NULLS FIRST/LAST) or its leading column order does not match what the join requires, so it cannot supply the ordering.
- work_mem too small for the sorts feeding the join, causing external merge sorts on disk.
- A row underestimate that made the planner believe the sorts would be small and cheap.
- Low physical correlation between the index order and the heap order, making an index scan expensive enough that the planner prefers a sequential scan plus sort.
- A join key with a collation or type difference between the two sides, preventing merge join from using existing index ordering.

## 5. Investigation Strategy

1. Identify statements writing temporary blocks, since sorts feeding a merge join are a common source.
2. Inspect the indexes on the join tables and check whether any of them can supply the required ordering on the join key.
3. Inspect the column statistics, especially correlation, which determines how attractive an ordered index scan looks to the planner.
4. Review the settings governing merge join, sorting, and incremental sort.
5. Capture the plan under the guarded runbook to see whether Sort nodes dominate and whether they spill.

## 6. Prerequisites

- Role membership in pg_monitor (or pg_read_all_stats).
- pg_stat_statements for statement-level temporary block attribution.
- The identity of the join under investigation and the tables and columns it joins on.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_sort_and_temp_heavy_statements.sql`](scripts/01_sort_and_temp_heavy_statements.sql) -- Identifies statements writing temporary blocks, including sorts that feed a merge join.
2. [`scripts/02_join_key_index_coverage.sql`](scripts/02_join_key_index_coverage.sql) -- Lists the indexes on the join table and their exact definitions, to determine whether any can supply sorted input.
3. [`scripts/03_join_column_correlation.sql`](scripts/03_join_column_correlation.sql) -- Shows per-column statistics, especially physical correlation, for the join columns.
4. [`scripts/04_sort_and_join_settings.sql`](scripts/04_sort_and_join_settings.sql) -- Reviews the settings that govern merge join selection, sorting, and incremental sort.
5. [`scripts/05_inspect_merge_join_plan.md`](scripts/05_inspect_merge_join_plan.md) -- Guarded runbook for reading a merge join plan and deciding between adding an index and adding memory.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Ordered index scans issue many small random reads, which on Aurora's network-attached storage are more expensive relative to sequential reads than on local NVMe. effective_io_concurrency and random_page_cost therefore materially influence whether the planner chooses the ordered index scan that makes merge join worthwhile.
- The sorts feeding a merge join spill to local instance storage, whose capacity is a property of the instance class rather than of the shared cluster volume.
- A dedicated Aurora reader with its own parameter group is the natural home for large merge-join batch jobs: it can carry a work_mem sized for sorting without exposing the writer's order path to the same risk.

## 8. Interpretation Guide

- A merge join fed by two Index Scans with no Sort nodes is the good case and generally needs no intervention, even on very large inputs, because it streams rather than materializing.
- A merge join fed by Sort nodes is only worthwhile if the sorts are cheap. Read Sort Method in the plan: 'quicksort  Memory: NkB' is in-memory and fine, while 'external merge  Disk: NkB' means the sort spilled and the join is now I/O-bound.
- PostgreSQL 13 and later can use an Incremental Sort when an index provides a prefix of the required ordering, sorting only within groups. Seeing Incremental Sort in the plan means a partially useful index exists and extending it to cover the full ordering may remove the sort entirely.
- The correlation statistic per column indicates how closely physical row order matches logical order: values near 1 or -1 make an ordered index scan cheap, values near 0 make it look expensive and push the planner toward sequential scan plus sort.
- Index sort direction matters: an index defined ASC NULLS LAST cannot supply DESC NULLS FIRST ordering directly. Read pg_get_indexdef output carefully rather than assuming any index on the column will do.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- For a batch job that must complete now, raise work_mem for that session alone so the feeding sorts stay in memory.

**Short-term remediation** (hours to days):

- Create the index that supplies sorted input on the join key, with matching column order and sort direction, built CONCURRENTLY.
- Run a targeted ANALYZE if statistics are stale, so the planner's estimate of the sort size and of the index scan cost is correct.
- Raise work_mem for the reporting or batch role specifically, rather than globally.

**Long-term engineering fix** (days to weeks):

- Align the physical clustering of the large time-ordered tables with their natural join and scan order (for example by partitioning by time), so correlation stays high and ordered index scans stay cheap as the tables grow.
- Standardize join key types and collations across the schema so index ordering is always usable for merge joins.
- Move large analytical joins onto dedicated readers where a generous work_mem is safe.

## 10. Production Safety

- All .sql scripts here are read-only and safe at any time.
- Plan capture that executes the statement is a guarded runbook step. Deciding to actually execute a candidate production query is an operator judgement call, not something an investigation script may do on the operator's behalf. That is why every EXPLAIN ANALYZE step in this toolkit is a markdown runbook rather than a .sql file.
- Creating an index to supply sorted input is a schema change: build it CONCURRENTLY and follow the schema-changes safety guidance, because a non-concurrent build takes a lock that blocks writes to the table for its entire duration.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- The required index would be large enough to materially affect write latency on a hot exchange table -- escalate for a cost/benefit decision rather than adding it unilaterally.
- The join cannot avoid sorting and the sorts cannot fit in a reasonable work_mem, meaning the data model or the job design must change.
- A settlement or reconciliation job is missing its processing window as a direct result -- escalate with the operational deadline made explicit.

## 12. Related Issues

- [sort-spills](../sort-spills/README.md)
- [hash-join-analysis](../hash-join-analysis/README.md)
- [analyze-query-plan](../analyze-query-plan/README.md)
- [inefficient-index-usage](../inefficient-index-usage/README.md)
- [missing-index-candidates](../../tables-and-indexes/missing-index-candidates/README.md)
