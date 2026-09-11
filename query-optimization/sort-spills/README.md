# Sort Spills to Disk

**Category:** Query Optimization | **Workflow:** `query-optimization/sort-spills`

## 1. Problem Description

When a sort does not fit in work_mem, PostgreSQL switches from an in-memory quicksort to an external merge sort that writes runs to temporary files and merges them back. The query still returns correct results, silently, several times slower. On an exchange this hits ORDER BY on trade and order history, window functions over ledger entries, DISTINCT and GROUP BY on large result sets, and the sorts that feed merge joins. This workflow finds the spilling statements, decides whether the answer is memory, an index, or a smaller input, and guards the memory experiment.

## 2. Typical Symptoms

- Rising temp_bytes on the instance with no corresponding change in query volume.
- A paginated history endpoint (order history, trade history, ledger export) that is fast for recent pages and slow for deep ones.
- An EXPLAIN ANALYZE plan showing 'Sort Method: external merge  Disk: NkB'.
- Reporting queries whose runtime grew sharply once a table crossed a size threshold, with no plan change.

## 3. Business Impact

- A spilled sort converts a memory-speed operation into local-disk I/O, typically multiplying the statement's runtime several-fold and consuming I/O capacity shared with the trading workload.
- Deep pagination over trade history is a common exchange pattern and a common spill source: the database sorts a very large result set to return the fiftieth page of it.
- Concurrent spills compete for finite local instance storage, so several large sorts at once can fail outright rather than merely slow down.

## 4. Possible Root Causes

- work_mem too small for the sort's input size -- the direct cause of every spill.
- A row underestimate making the planner believe the sort would be small, so it chose a plan requiring a sort at all.
- No index providing the required ordering, forcing an explicit sort where an ordered index scan would have needed none.
- OFFSET-based deep pagination, which sorts the entire result set to discard most of it.
- Parallel query multiplying memory demand: each worker performs its own sort with its own work_mem allocation.
- Wide rows being sorted: selecting many columns, or large text and JSON payloads, inflates the sort's memory footprint far beyond what the row count suggests.

## 5. Investigation Strategy

1. Identify the statements writing the most temporary blocks.
2. Quantify the cluster-wide temp file trend to distinguish a systemic memory-sizing problem from one bad query.
3. Review the memory settings that determine the spill threshold, including the parallel worker multiplier.
4. Check whether an index could supply the ordering and remove the sort altogether.
5. Capture the plan under the guarded runbook to read Sort Method and size the minimum sufficient work_mem.

## 6. Prerequisites

- Role membership in pg_monitor (or pg_read_all_stats).
- pg_stat_statements for statement-level temporary block attribution.
- log_temp_files set to 0 is strongly recommended so every spill is logged with its size and statement; on Aurora those log lines are exported to CloudWatch Logs.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_statements_spilling_to_disk.sql`](scripts/01_statements_spilling_to_disk.sql) -- Ranks statements by temporary block volume to find those whose sorts are spilling.
2. [`scripts/02_temp_file_volume_trend.sql`](scripts/02_temp_file_volume_trend.sql) -- Measures cluster-wide temporary file volume to judge whether spilling is systemic.
3. [`scripts/03_sort_memory_settings.sql`](scripts/03_sort_memory_settings.sql) -- Reviews the memory and logging settings that determine when a sort spills and whether it is recorded.
4. [`scripts/04_ordering_index_coverage.sql`](scripts/04_ordering_index_coverage.sql) -- Checks whether an index could supply the required ordering and remove the sort entirely.
5. [`scripts/05_size_sort_memory_safely.md`](scripts/05_size_sort_memory_safely.md) -- Guarded runbook for confirming a sort spill and choosing between an index, a smaller input, and more memory.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Temporary files are written to local instance storage, not to the shared Aurora cluster volume, so their capacity is bounded by the instance class and exhausting it produces query errors rather than cluster storage growth.
- work_mem is changed through the Aurora DB cluster or DB instance parameter group; ALTER SYSTEM is unavailable. A per-role default set with ALTER ROLE is the targeted alternative and takes effect without a reboot.
- A dedicated reader with its own DB instance parameter group can carry a large work_mem for reporting without exposing the writer to the same memory risk -- the cleanest Aurora-native separation for spill-heavy analytical work.

## 8. Interpretation Guide

- 'Sort Method: quicksort  Memory: NkB' means the sort fit in memory and there is nothing to fix. 'external merge  Disk: NkB' means it spilled, and the Disk figure tells you roughly how much memory would have been needed to avoid it.
- The Disk figure is not the required work_mem directly -- the on-disk representation differs from the in-memory one -- but it is the right order of magnitude for choosing the next value to test.
- An index that provides the required ordering removes the sort entirely and permanently, at every data volume. That is almost always a better answer than granting more memory, which only postpones the spill until the table grows.
- Deep OFFSET pagination cannot be fixed with memory: sorting a million rows to return rows 900,000 to 900,050 is inherent to the query shape. Keyset pagination (WHERE (created_at, id) < (:last_seen_at, :last_seen_id) ORDER BY created_at DESC, id DESC LIMIT 50) removes both the sort and the offset scan.
- work_mem applies per sort node and per parallel worker. A statement with two sorts across four workers can allocate eight times work_mem at once, which is why a global increase is far riskier than it appears.
- A sort that spills only occasionally is parameter-sensitive: it is fine for a narrow date range and spills for a wide one. Size the fix for the realistic worst case, not the average.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- For a report that must complete now, raise work_mem in that session alone before running it.

**Short-term remediation** (hours to days):

- Add the index that supplies the required ordering so no sort is needed, built CONCURRENTLY.
- Raise work_mem for the specific reporting or batch role rather than cluster-wide.
- Run a targeted ANALYZE if a row underestimate caused the planner to choose a sort-based plan it should not have chosen.
- Reduce the sorted row width by selecting only the needed columns, which can pull a borderline sort back into memory at no cost.

**Long-term engineering fix** (days to weeks):

- Replace OFFSET pagination with keyset pagination on the exchange's history endpoints -- it removes the sort and the discarded scan work simultaneously.
- Move analytical and export workloads onto dedicated Aurora readers with a parameter group sized for sorting.
- Partition the large history tables by time so ordered scans and sorts naturally operate on bounded partitions.

## 10. Production Safety

- All .sql scripts here are read-only.
- Testing a larger work_mem is a guarded runbook step because the setting multiplies across sort nodes, parallel workers, and concurrent connections; an unconsidered global increase is a direct route to instance memory exhaustion. Deciding to actually execute a candidate production query is an operator judgement call, not something an investigation script may do on the operator's behalf. That is why every EXPLAIN ANALYZE step in this toolkit is a markdown runbook rather than a .sql file.
- Prefer reproducing a spilling read-only statement on a reader instance, where the temporary file I/O does not compete with the order path on the writer.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Local instance storage is close to exhaustion from concurrent temporary files -- this fails queries outright and must be escalated immediately.
- A settlement, reconciliation, or regulatory export cannot complete within its window even with a reasonable memory allocation.
- The sort is inherent to the query shape (deep pagination, an unbounded export) and needs an application-side change rather than database tuning.

## 12. Related Issues

- [temp-file-investigation](../temp-file-investigation/README.md)
- [hash-join-analysis](../hash-join-analysis/README.md)
- [merge-join-analysis](../merge-join-analysis/README.md)
- [analyze-query-plan](../analyze-query-plan/README.md)
- [high-iops](../../performance/high-iops/README.md)
