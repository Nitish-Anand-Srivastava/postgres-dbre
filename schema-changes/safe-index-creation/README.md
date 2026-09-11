# Safe Index Creation

**Category:** Schema Changes and DDL | **Workflow:** `schema-changes/safe-index-creation`

## 1. Problem Description

A new index is needed on a production table and the question is how to build it without blocking the trading path. This is the entry point for the whole index-creation family: it establishes whether the index is genuinely needed (a surprising proportion of proposed indexes are already covered by an existing one), which build method is appropriate for the table's size and write rate, and what the lock and rollback consequences of each option are. The single most important decision it drives is plain `CREATE INDEX` versus `CREATE INDEX CONCURRENTLY` -- the first takes a lock that blocks every write to the table for the entire build, and the second does not, at the cost of being slower, non-transactional, and able to fail in a way that leaves an unusable index behind.

## 2. Typical Symptoms

- A slow query investigation has identified a missing index on a large table such as orders, trades, or ledger_entries.
- A foreign key on a child table has no supporting index and parent deletes are performing sequential scans.
- A new feature or reporting requirement introduces an access pattern the current index set does not serve.
- A previous index build was attempted, blocked the application, and had to be cancelled.

## 3. Business Impact

- Building an index the wrong way on the orders table blocks every insert and update for the duration of the build -- on a multi-hundred-GB table that is an outage measured in hours, not seconds.
- Not building a needed index leaves the query it would serve doing sequential scans, which degrades continuously as the table grows.
- A failed build leaves an INVALID index consuming full storage and full write overhead while providing zero query benefit.
- Every additional index permanently increases write amplification on the hottest write path in the exchange, so an unnecessary index is a lasting cost, not a neutral one.

## 4. Possible Root Causes

- N/A -- this is a planned change workflow, not an incident investigation. The inputs come from query-optimization and tables-and-indexes.

## 5. Investigation Strategy

1. Inventory the indexes and constraints that already exist on the target table -- the proposed index is frequently already covered by the leading columns of an existing one.
2. Measure the table's size, row count, and maintenance state to estimate build duration and decide which build method is viable.
3. Check for existing duplicate indexes on the table, since adding another near-duplicate compounds an existing problem.
4. Read the timeout and maintenance-memory settings that will govern the build's behavior when it cannot get its lock immediately.
5. Choose the build method and execute it through the runbook, with the lock consequences understood before the first statement.
6. Validate afterwards that the index is valid, is being used, and has not left anything behind.

## 6. Prerequisites

- A specific, justified index definition -- the query it serves should be named in the change ticket, not inferred afterwards.
- Table ownership or `MAINTAIN` privilege on the target table for the build itself; `pg_monitor` is sufficient for all the investigation scripts.
- Agreement on the build method and, if a blocking build is chosen, an agreed window.
- Enough free storage for the new index, plus awareness that on Aurora the space consumed permanently raises the volume high-water mark.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_existing_index_and_constraint_inventory.sql`](scripts/01_existing_index_and_constraint_inventory.sql) -- Inventories every index and constraint already on the target table, to establish whether the proposed index is genuinely new.
2. [`scripts/02_target_table_size_and_state.sql`](scripts/02_target_table_size_and_state.sql) -- Measures the target table's size, row estimates, and maintenance recency to estimate build duration and choose a build method.
3. [`scripts/03_duplicate_index_check.sql`](scripts/03_duplicate_index_check.sql) -- Checks the database for structurally duplicate indexes, so a new index is not added to a table that already has a redundancy problem.
4. [`scripts/04_ddl_safety_settings.sql`](scripts/04_ddl_safety_settings.sql) -- Reads the timeout, memory, and parallelism settings that will govern the build's behavior and its blast radius if it cannot get its lock.
5. [`scripts/05_safe_index_creation_runbook.md`](scripts/05_safe_index_creation_runbook.md) -- The guarded DDL runbook for creating an index, documenting lock level, blocking risk, transaction behavior, rollback, and production considerations for each method.
6. [`scripts/06_post_build_validation.sql`](scripts/06_post_build_validation.sql) -- Confirms after the build that the index is valid, that no build is still running, and that nothing was left behind.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Index builds run on the Aurora writer and generate substantial redo against the shared storage volume, which readers must apply. Expect reader lag to rise during a large build and schedule accordingly.
- The storage consumed by a new index permanently raises the Aurora volume high-water mark. Even if the index is later dropped, the volume does not shrink.
- `maintenance_work_mem` and `max_parallel_maintenance_workers` are set through the Aurora DB cluster or instance parameter group. A session-level `SET maintenance_work_mem` before a build is the least invasive way to give one build more memory.
- An Aurora failover during a `CREATE INDEX CONCURRENTLY` will abort the build and leave an INVALID index behind on the new writer -- check for one after any unplanned failover that coincided with a build.

## 8. Interpretation Guide

- Before anything else, check whether an existing index already leads with the same column(s). PostgreSQL can use a multi-column index for queries filtering only on its leading columns, so an index on `(account_id, created_at)` already serves queries filtering on `account_id` alone and a separate single-column index would be pure duplication.
- Table size drives build duration, but write rate drives risk. A 50 GB table with light writes can tolerate a blocking build during a quiet hour; a 5 GB table taking ten thousand inserts a second cannot tolerate one at any hour.
- `maintenance_work_mem` is the main lever on build speed. A build that spills its sort to disk is dramatically slower, and on Aurora that spill consumes per-instance local storage.
- `max_parallel_maintenance_workers` above zero lets a plain `CREATE INDEX` use parallel workers. Note that `CREATE INDEX CONCURRENTLY` does not benefit from this in the same way, which is part of why it is slower.
- `lock_timeout` is the single most important safety setting for any blocking build: without it, a build that cannot acquire its lock queues, and every subsequent query on the table queues behind the build. With it, the build fails fast and harmlessly.
- If the table is partitioned, a `CREATE INDEX` on the parent recurses into every partition and holds locks across all of them. Build per-partition indexes concurrently and attach them instead -- this is covered in the runbook.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If a running index build is blocking the application right now, cancel it at the session level and let the partial work roll back. This is safe for a plain `CREATE INDEX` (it rolls back cleanly) and leaves an INVALID index behind for a concurrent build, which is then cleaned up via the failed-index-build workflow.

**Short-term remediation** (hours to days):

- Build the index using the concurrent method documented in the runbook, which is the correct default for any production table on a 24/7 trading platform.
- Set `lock_timeout` on the session before any blocking DDL so a lock queue can never form behind it.
- Validate the index is being used after the build, and drop it if the query it was built for does not actually pick it up.

**Long-term engineering fix** (days to weeks):

- Make index review part of schema change review: every proposed index names its query and confirms no existing index covers the access pattern.
- Prefer partial indexes where the workload only queries a subset (an index on open orders is a fraction of the size of one on all orders).
- Adopt a standard index build procedure so the concurrent method is the default rather than a decision made under pressure each time.

## 10. Production Safety

- All `.sql` scripts in this workflow are read-only catalog and statistics queries and are safe to run at any time.
- The DDL lives exclusively in the `.md` runbook and must be executed statement by statement by an operator who has read it, never piped into psql.
- Never run a plain `CREATE INDEX` against a production table on the trading path. It holds a `ShareLock` that blocks every INSERT, UPDATE, and DELETE on the table for the entire build.
- `CREATE INDEX CONCURRENTLY` cannot run inside a transaction block. Do not wrap it in `BEGIN`/`COMMIT`, and be aware that many migration frameworks open a transaction implicitly -- that is the single most common reason concurrent builds fail in deployment pipelines.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- The target table is on the live order-matching or wallet-balance path and a blocking build is being proposed -- this needs explicit sign-off, not a DBA decision.
- The estimated build duration exceeds the agreed window, or the table is large enough that the concurrent build will run for many hours across a market event.
- The table is partitioned with a large number of partitions, which turns one index build into hundreds and needs a coordinated plan.
- A previous build attempt failed and its cause is not understood -- resolve that through the failed-index-build workflow before retrying.

## 12. Related Issues

- [concurrent-index-build](../concurrent-index-build/README.md)
- [add-index-large-table](../add-index-large-table/README.md)
- [failed-index-build](../failed-index-build/README.md)
- [drop-index-safely](../drop-index-safely/README.md)
- [ddl-lock-investigation](../ddl-lock-investigation/README.md)
- [missing-index-candidates](../../tables-and-indexes/missing-index-candidates/README.md)
- [duplicate-indexes](../../tables-and-indexes/duplicate-indexes/README.md)
- [ddl-blocking](../../concurrency-and-locking/ddl-blocking/README.md)
