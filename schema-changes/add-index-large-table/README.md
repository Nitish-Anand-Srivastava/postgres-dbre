# Adding an Index to a Large Table

**Category:** Schema Changes and DDL | **Workflow:** `schema-changes/add-index-large-table`

## 1. Problem Description

An index is needed on a table large enough that the build itself is a production event: hours of elapsed time, substantial redo, sustained Aurora reader lag, and a permanent increase in write amplification on every subsequent insert and update. This workflow is deliberately more sceptical than safe-index-creation. Before committing to the build it asks whether the index is justified at all -- is there real evidence of the sequential scans it would eliminate, is the access pattern already covered by an existing index's leading columns, and is the table's write rate high enough that the ongoing maintenance cost outweighs the query benefit. Only then does it cover the build, which on a table this size must always be concurrent and should usually be partial.

## 2. Typical Symptoms

- A query against a multi-hundred-gigabyte table is doing a sequential scan and the latency is no longer acceptable.
- A foreign key on a large child table has no supporting index, so parent deletes scan the whole child.
- Query latency on a large table is degrading steadily as the table grows, with no plan change.
- A new reporting or compliance requirement introduces an access pattern the current index set does not serve.
- A previous attempt to build an index on this table was abandoned because of its duration or its impact on reader lag.

## 3. Business Impact

- Sequential scans on a large exchange table consume disproportionate I/O and buffer cache, degrading latency for every other query on the instance, not just the slow one.
- The build itself generates hours of sustained redo, raising Aurora reader lag and risking customer-visible stale balances and order states.
- Every index permanently increases write amplification on the table's insert and update path, which on the trading path is the most latency-sensitive operation the exchange performs.
- The index permanently raises the Aurora volume high-water mark, and dropping it later does not reduce the bill.

## 4. Possible Root Causes

- N/A -- this is a planned change workflow. The evidence for the change comes from query-optimization and tables-and-indexes.

## 5. Investigation Strategy

1. Establish the evidence: which tables are actually suffering from sequential scans, and how expensive those scans are.
2. Check whether the access pattern is already covered by an existing index's leading columns -- a surprising proportion of proposed indexes are redundant.
3. Measure the table's write volume, because that is what determines the ongoing cost of the new index rather than its one-off build cost.
4. Measure the table's size to estimate build duration and storage impact.
5. Build concurrently through the runbook, considering a partial or covering index rather than a plain one.
6. Monitor the build, then confirm afterwards that the index is valid and is actually being used.

## 6. Prerequisites

- Concrete evidence that the index is needed -- a specific slow query with a plan showing the sequential scan, named in the change ticket.
- Table ownership or `MAINTAIN` privilege for the build; `pg_monitor` for the investigation.
- `pg_stat_statements` is helpful for identifying the queries involved but is not required by these scripts.
- Enough free storage for the new index, and acceptance that the Aurora volume high-water mark rises permanently.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_sequential_scan_evidence.sql`](scripts/01_sequential_scan_evidence.sql) -- Establishes whether there is real evidence of expensive sequential scans justifying a new index on a large table.
2. [`scripts/02_existing_index_inventory.sql`](scripts/02_existing_index_inventory.sql) -- Checks whether the proposed access pattern is already covered by an existing index's leading columns.
3. [`scripts/03_write_volume_and_hot_ratio.sql`](scripts/03_write_volume_and_hot_ratio.sql) -- Measures the table's write volume and HOT update ratio, which determine the ongoing cost of the new index.
4. [`scripts/04_target_table_size.sql`](scripts/04_target_table_size.sql) -- Measures the target table to estimate build duration and the storage the new index will consume.
5. [`scripts/05_large_table_index_build_runbook.md`](scripts/05_large_table_index_build_runbook.md) -- The guarded DDL runbook for building an index on a very large table, including partial and covering index alternatives.
6. [`scripts/06_build_progress_and_validity.sql`](scripts/06_build_progress_and_validity.sql) -- Monitors the build while it runs and confirms afterwards that the index is valid and nothing was left behind.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- A large index build generates sustained redo against the Aurora shared storage volume, which every reader applies. Monitor CloudWatch `AuroraReplicaLag` throughout and treat customer-visible lag as grounds to cancel.
- The new index permanently raises the Aurora volume high-water mark. Dropping it later frees space for reuse but does not reduce billed storage.
- `SET maintenance_work_mem` at session level is the least invasive way to give one build more memory on Aurora, and keeping the build's sort in memory materially shortens the exposure window.
- An Aurora failover during the build aborts it and leaves an INVALID index on the new writer -- budget for that possibility on a build measured in hours.

## 8. Interpretation Guide

- A high `seq_scan` count alone is not evidence. Small lookup tables are scanned sequentially by design and that is faster than an index. What matters is `seq_tup_read` relative to table size -- large numbers of rows read per scan on a large table is the pattern worth fixing.
- Check the existing index list before accepting that a new index is needed. PostgreSQL uses a multi-column index for queries filtering only on its leading columns, so an index on `(account_id, executed_at)` already serves a filter on `account_id` alone.
- Write volume determines the ongoing cost. On a table taking millions of inserts a day, each additional index is millions of extra index entries written, WAL-logged, replicated, and vacuumed daily -- forever. Weigh that against the query benefit explicitly rather than assuming the index is free.
- A low `pct_hot_updates` on the target table is a warning: the new index may make it worse. Every additional index reduces the chance of a HOT update, because HOT requires that no indexed column changed and that the new row version fits on the same page.
- A partial index is usually the right answer on a large table. An index on open orders is a tiny fraction of the size of one on all orders, builds in a fraction of the time, and costs far less to maintain -- because rows outside the predicate are not indexed at all.
- A covering index with `INCLUDE` can turn a heap fetch into an index-only scan, but it makes the index larger and is only worth it when the query genuinely returns those columns.
- Estimate build duration from table size, then double or triple it for the concurrent form, which makes two passes plus two waits for older transactions.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If a build is causing customer-visible reader lag, cancel it and clean up the INVALID index afterwards. Lag affecting customers outranks a query improvement.

**Short-term remediation** (hours to days):

- Build the index concurrently through the runbook, preferring a partial index where the workload only queries a subset.
- Verify after the build that the query actually uses the new index -- if it does not, drop it rather than leaving a permanent write cost with no benefit.
- If the build is not viable at this size, consider whether partitioning the table first makes both this index and every future one cheaper.

**Long-term engineering fix** (days to weeks):

- Partition the largest tables so index builds are per-partition operations rather than whole-table events.
- Review the full index set on the table as a unit whenever adding to it, rather than only evaluating the new index in isolation.
- Track index usage over time so indexes that stop earning their keep are found and removed.

## 10. Production Safety

- All `.sql` scripts here are read-only. The build DDL lives in the `.md` runbook.
- On a table this size, only the concurrent build form is acceptable. A plain `CREATE INDEX` would block every write for hours.
- `CREATE INDEX CONCURRENTLY` cannot run inside a transaction block, and most migration frameworks open one implicitly -- verify before starting.
- Monitor Aurora reader lag throughout the build and be prepared to cancel. Plan for the cleanup a cancellation requires before you begin.
- Do not start a build immediately before a known market event, a deployment, or a scheduled failover test.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- The build's estimated duration spans a market event or a scheduled deployment window.
- Reader lag during the build reaches a level that affects customer-facing reads -- treat as an incident and cancel.
- The table is large enough that the build cannot realistically complete in any acceptable window, which means the answer is partitioning rather than indexing.
- The proposed index would be the tenth or more on a table on the trading path -- that needs an index-set review, not another addition.

## 12. Related Issues

- [concurrent-index-build](../concurrent-index-build/README.md)
- [safe-index-creation](../safe-index-creation/README.md)
- [failed-index-build](../failed-index-build/README.md)
- [drop-index-safely](../drop-index-safely/README.md)
- [missing-index-candidates](../../tables-and-indexes/missing-index-candidates/README.md)
- [sequential-scan-investigation](../../tables-and-indexes/sequential-scan-investigation/README.md)
- [index-growth](../../storage-and-capacity/index-growth/README.md)
- [inefficient-index-usage](../../query-optimization/inefficient-index-usage/README.md)
