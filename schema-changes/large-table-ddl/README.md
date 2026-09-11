# DDL on a Large Production Table

**Category:** Schema Changes and DDL | **Workflow:** `schema-changes/large-table-ddl`

## 1. Problem Description

A schema change is needed on a table large enough and hot enough that the usual answer -- just run the ALTER -- is unacceptable. The governing insight is that on a live exchange the lock is the risk, not the work: PostgreSQL takes an `AccessExclusiveLock` for most `ALTER TABLE` variants, and while that lock is held every query against the table -- including plain SELECTs on the order-matching path -- queues behind it. Worse, a *pending* exclusive lock request blocks every later request too, so a statement that merely waits for its lock takes the application down just as effectively as one that holds it. This workflow classifies the intended change by lock level and rewrite behavior, checks the table is in a state where DDL can safely be attempted, and executes it with the lock-timeout-and-retry discipline that makes the difference between a routine change and an outage.

## 2. Typical Symptoms

- A schema change is required on a table in the hundreds of gigabytes, such as orders, trades, or ledger_entries.
- A previous `ALTER TABLE` on this table had to be cancelled because it blocked the application.
- A deployment is blocked pending a schema change nobody is willing to run during trading hours.
- An `ALTER TABLE` is currently queued waiting for a lock and the application is timing out.
- The change involves a column type change, a new `NOT NULL` constraint, or a new foreign key -- all of which have non-obvious rewrite and validation behavior.

## 3. Business Impact

- An `AccessExclusiveLock` on the orders table blocks order placement and cancellation entirely for as long as it is held -- on a rewriting DDL against a large table that can be many minutes or hours.
- A DDL statement waiting for a lock is just as damaging as one holding it, because every subsequent query queues behind the pending request. This is the mechanism behind most 'the database froze for no reason' incidents.
- A table rewrite doubles the table's storage for the duration, and on Aurora that peak permanently raises the volume high-water mark.
- Deferring necessary schema changes indefinitely because they are considered too dangerous accumulates technical debt that eventually forces a riskier, larger migration.

## 4. Possible Root Causes

- N/A -- this is a planned change workflow. The risk being managed comes from table size, write rate, and the specific lock level of the chosen statement.

## 5. Investigation Strategy

1. Measure the target table precisely: size, row estimate, index count, and maintenance state, which together determine rewrite duration.
2. Inventory every dependent object -- indexes, constraints, incoming foreign keys, views, triggers -- because each may need attention after the change.
3. Check the current lock picture on the table, so the change is not attempted into an existing lock queue.
4. Check for long-running transactions, which are the usual reason a DDL statement cannot get its lock.
5. Read the timeout settings that determine whether a failed lock acquisition is harmless or catastrophic.
6. Classify the intended statement using the lock-level and rewrite reference before choosing an execution strategy.
7. Execute through the runbook using lock timeout and retry, never as a bare statement.

## 6. Prerequisites

- Table ownership or equivalent DDL privilege; `pg_monitor` is sufficient for all investigation scripts.
- A precise statement of the intended change -- the exact `ALTER TABLE` text, not a description of the goal.
- A change ticket, a rollback plan, and a second engineer present for the execution.
- Enough free storage for a full table rewrite if the classification reference says the statement rewrites.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_target_table_size_and_state.sql`](scripts/01_target_table_size_and_state.sql) -- Measures the target table precisely, since size and index count are what determine how long any rewriting statement will hold its lock.
2. [`scripts/02_dependent_objects_inventory.sql`](scripts/02_dependent_objects_inventory.sql) -- Inventories every index, constraint, incoming foreign key, view, and trigger that depends on the target table.
3. [`scripts/03_current_lock_activity.sql`](scripts/03_current_lock_activity.sql) -- Shows the current DDL-style lock picture so a change is not attempted into an existing lock queue.
4. [`scripts/04_long_running_transactions.sql`](scripts/04_long_running_transactions.sql) -- Finds the long-running transactions that are the usual reason a DDL statement cannot acquire its lock.
5. [`scripts/05_lock_level_and_rewrite_reference.md`](scripts/05_lock_level_and_rewrite_reference.md) -- Reference classification of every common ALTER TABLE variant by lock level, rewrite behavior, table scan, and safe alternative.
6. [`scripts/06_large_table_ddl_execution_runbook.md`](scripts/06_large_table_ddl_execution_runbook.md) -- The guarded execution runbook: lock-timeout-and-retry for fast DDL, the two-step pattern for constraints, and build-alongside-and-swap for rewrites.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- A table rewrite generates WAL proportional to the entire table, which every Aurora reader must apply from the shared storage volume. Expect substantial reader lag during a rewrite of a large table and plan for stale reads while it runs.
- The temporary second copy created by a rewrite permanently raises the Aurora volume high-water mark, even after the original is dropped. Budget for the peak, not the steady state.
- Aurora does not support `ALTER SYSTEM` for most parameters -- `lock_timeout` and friends are set in the DB cluster parameter group or, better for DDL, at session level with `SET`.
- An Aurora failover during a rewriting `ALTER TABLE` rolls the statement back entirely, since DDL is transactional. That is safe, but it means a long rewrite is exposed to any failover during its whole duration.

## 8. Interpretation Guide

- Classify the statement before anything else. The three questions are: what lock level does it take, does it rewrite the table, and does it scan the table to validate. A statement that takes `AccessExclusiveLock` but neither rewrites nor scans holds that lock for milliseconds and is essentially safe with a lock timeout. One that rewrites holds it for the duration of the rewrite and is not safe at any size that matters.
- `ShareUpdateExclusiveLock` (taken by `CREATE INDEX CONCURRENTLY`, `DROP INDEX CONCURRENTLY`, `ALTER TABLE ... SET STATISTICS`, `VALIDATE CONSTRAINT`) does not block reads or writes. This is the lock level you want, and several otherwise-blocking operations have a two-step form that lets you reach it.
- The pending-lock queue is the mechanism most people miss. When a DDL statement waits for `AccessExclusiveLock`, PostgreSQL queues every subsequent lock request behind it -- including plain SELECTs that would not have conflicted with the existing holders. One long-running read can therefore turn a waiting `ALTER TABLE` into a total application stall.
- This makes `lock_timeout` non-negotiable for production DDL. With a short timeout the statement either gets its lock immediately or fails harmlessly; without one it can take the application down while doing nothing at all.
- A table rewrite needs free space for a full second copy and generates WAL proportional to the entire table. On a multi-hundred-GB exchange table that is both a storage event and a replication event, not just a locking one.
- Several expensive operations have a cheap two-step alternative: add a `CHECK` constraint `NOT VALID` (brief exclusive lock, no scan) then `VALIDATE CONSTRAINT` (`ShareUpdateExclusiveLock`, scans without blocking). The same pattern applies to foreign keys. Reach for this before accepting a long blocking scan.
- If the table is partitioned, DDL on the parent recurses into every partition and holds locks across all of them at once. Always evaluate whether the change can be applied per-partition instead.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If an `ALTER TABLE` is currently queued and the application is stalling, cancel that statement immediately. The lock queue drains as soon as the pending request is withdrawn, and the application recovers within seconds.
- Do not attempt to fix a stalled DDL by adding more DDL. Cancel, let the queue drain, investigate, then retry with a lock timeout.

**Short-term remediation** (hours to days):

- Re-run the change with `SET lock_timeout` and a retry loop, so it either acquires the lock immediately or fails without forming a queue.
- Split the change into its non-blocking equivalents where one exists -- `NOT VALID` plus `VALIDATE`, or the build-alongside-and-swap pattern for a rewrite.
- Clear the long-running transactions that are preventing lock acquisition, then retry.

**Long-term engineering fix** (days to weeks):

- Adopt the lock-timeout-and-retry pattern as the standard for all production DDL, enforced in the migration framework rather than remembered by individuals.
- Partition the largest tables so that future DDL can be applied one partition at a time instead of to a single monolithic relation.
- Add a schema-change review step that classifies every migration by lock level and rewrite behavior before it is approved.
- Set `idle_in_transaction_session_timeout` cluster-wide so leaked connections cannot indefinitely block schema changes.

## 10. Production Safety

- All `.sql` scripts here are read-only. Every DDL statement lives in the two `.md` runbooks and must be executed by hand, one statement at a time.
- Never issue DDL against a large production table without `lock_timeout` set. This is the single most important rule in this category.
- Never run a rewriting `ALTER TABLE` on a large exchange table during trading hours. Use the build-alongside-and-swap pattern instead.
- Check for long-running transactions immediately before executing, not an hour earlier -- the picture changes constantly.
- On a partitioned table, verify whether the statement recurses to partitions before running it on the parent.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- The change requires a full table rewrite on a table on the live trading path -- this needs a migration design, not a single statement, and should go through the partitioning or archival migration patterns.
- An `ALTER TABLE` has already caused an application stall and the cause is not fully understood -- stop and investigate through ddl-lock-investigation before retrying.
- The table has incoming foreign keys from tables owned by other teams that must be coordinated with.
- The estimated rewrite duration exceeds any window the business is willing to accept, meaning the approach itself must change.

## 12. Related Issues

- [ddl-lock-investigation](../ddl-lock-investigation/README.md)
- [column-type-change](../column-type-change/README.md)
- [add-column-large-table](../add-column-large-table/README.md)
- [add-index-large-table](../add-index-large-table/README.md)
- [ddl-blocking](../../concurrency-and-locking/ddl-blocking/README.md)
- [blocked-queries](../../concurrency-and-locking/blocked-queries/README.md)
- [long-running-transactions](../../concurrency-and-locking/long-running-transactions/README.md)
- [partition-existing-large-table](../../partitioning/partition-existing-large-table/README.md)
