# Concurrent Index Build

**Category:** Schema Changes and DDL | **Workflow:** `schema-changes/concurrent-index-build`

## 1. Problem Description

`CREATE INDEX CONCURRENTLY` is the only index build method acceptable on a live exchange table, and it has a specific set of failure modes that have nothing to do with the index itself. It takes two full passes over the table and, between and after those passes, waits for every transaction that started before each pass to finish. That means a single long-running or idle-in-transaction session anywhere in the database -- one that never touches the target table at all -- can stall the build indefinitely. It also cannot run inside a transaction block, which is the reason most deployment pipelines fail to run it. This workflow covers the pre-flight checks that prevent a stall, live monitoring of a build in progress, and validation afterwards.

## 2. Typical Symptoms

- A concurrent index build has been running for far longer than the table size suggests it should.
- `pg_stat_progress_create_index` shows the build parked in a 'waiting for' phase and making no progress.
- A migration fails with 'CREATE INDEX CONCURRENTLY cannot run inside a transaction block'.
- A build completed but the index is marked INVALID and the planner will not use it.
- Aurora reader lag climbs while an index build is running on the writer.
- Autovacuum on the target table stops running while a concurrent build is in progress.

## 3. Business Impact

- A stalled build holds a `ShareUpdateExclusiveLock` on the table for its whole life, which blocks autovacuum on that table -- so a build stuck for hours on the trade tape is also hours of dead tuples accumulating unreclaimed.
- A build that has to be abandoned leaves an INVALID index consuming full storage and full write overhead for no benefit until someone notices and drops it.
- Extended builds generate sustained redo, raising reader lag and potentially serving stale balances and order states to customers.
- Repeated failed attempts delay the query improvement the index was meant to deliver, while the underlying slow query keeps degrading as the table grows.

## 4. Possible Root Causes

- Stall: a long-running transaction elsewhere in the database that the build must wait for before it can proceed past a phase boundary.
- Stall: an idle-in-transaction session -- doing nothing, blocking everything, usually a connection-pool leak or a forgotten terminal.
- Stall: an orphaned prepared transaction, which holds its snapshot indefinitely and survives restarts.
- Failure: the statement wrapped in an explicit or framework-implicit transaction block, which PostgreSQL rejects outright.
- Failure: a `statement_timeout` set at the session, role, or database level firing mid-build.
- Failure: a unique index build encountering a duplicate key that violates the proposed uniqueness constraint.
- Failure: a deadlock between the build and application traffic on the same table.
- Failure: an Aurora failover during the build, which aborts it and leaves an INVALID index on the new writer.
- Slowness: `maintenance_work_mem` too small, forcing the build's sort to spill to local storage.

## 5. Investigation Strategy

1. Before starting, find and clear anything that would stall the build: long-running transactions, idle-in-transaction sessions, prepared transactions.
2. Confirm the timeout settings will not kill the build mid-flight, and that no transaction wrapper will reject it outright.
3. Confirm the target table's size and existing index set so the expected duration is known before the clock starts.
4. Start the build through the runbook, outside any transaction block.
5. Monitor progress continuously via the progress view, paying particular attention to the phase rather than the percentage.
6. If the build stalls, identify the exact blocking backend and decide whether to wait or abandon.
7. Validate index validity afterwards and clean up if the build did not complete.

## 6. Prerequisites

- Table ownership or `MAINTAIN` privilege for the build itself; `pg_monitor` for all the monitoring scripts.
- A psql session or migration path that does not wrap the statement in a transaction -- verify this explicitly, because most frameworks do so by default.
- No `statement_timeout` in effect for the build session that is shorter than the expected build duration.
- Agreement that the build may need to be abandoned, and that doing so leaves cleanup work behind.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_preflight_blocking_transactions.sql`](scripts/01_preflight_blocking_transactions.sql) -- Finds the long-running transactions, idle-in-transaction sessions, and prepared transactions that would stall a concurrent build before it starts.
2. [`scripts/02_target_table_and_settings.sql`](scripts/02_target_table_and_settings.sql) -- Confirms the target table's size and the timeout settings that could kill the build mid-flight.
3. [`scripts/03_concurrent_index_build_runbook.md`](scripts/03_concurrent_index_build_runbook.md) -- The guarded DDL runbook for running a concurrent index build, with lock level, blocking risk, transaction behavior, rollback, and production considerations.
4. [`scripts/04_monitor_build_progress.sql`](scripts/04_monitor_build_progress.sql) -- Monitors an in-flight index build, showing its phase, progress, and the backend it is waiting on.
5. [`scripts/05_blocking_sessions_during_build.sql`](scripts/05_blocking_sessions_during_build.sql) -- Identifies the sessions a stalled build is waiting on, and what those sessions are actually doing.
6. [`scripts/06_post_build_validity_check.sql`](scripts/06_post_build_validity_check.sql) -- Confirms the finished index is valid and usable, or identifies the INVALID leftover if it was not.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- An Aurora failover aborts any in-flight concurrent index build. The new writer will have an INVALID index left behind -- always check after an unplanned failover that coincided with a build.
- The build's redo is applied by every Aurora reader from the shared storage volume, so reader lag is an expected side effect of a large build and should be monitored via CloudWatch `AuroraReplicaLag` throughout.
- Aurora does not expose `pg_stat_wal`, so the WAL generated by a build cannot be measured directly in SQL -- use CloudWatch `WriteThroughput` and `VolumeWriteIOPs` instead.
- `SET maintenance_work_mem` at session level works normally on Aurora and is the least invasive way to speed up one build without changing the cluster parameter group.

## 8. Interpretation Guide

- The `phase` column in the progress view is the diagnostic, not the percentage. 'building index' means real work is happening. 'waiting for writers before validation' or 'waiting for readers before marking dead' means the build is doing nothing at all and is waiting on older transactions -- no amount of patience helps until those finish.
- `current_locker_pid` names the exact backend the build is waiting on. That backend is your entire problem; look up what it is doing before considering any other explanation.
- A build waiting on a transaction that does not touch the target table is normal and is the most confusing part of this operation for people meeting it the first time. The build waits on transaction *age*, not on table access, because it needs a snapshot guarantee rather than a lock.
- `blocks_done` versus `blocks_total` tells you how far the current scan has progressed. Remember there are two scans, so reaching 100% once means roughly halfway.
- The `ShareUpdateExclusiveLock` the build holds conflicts with autovacuum on the same table. A build running for hours means hours without vacuum on that table, so check dead tuples after a long build completes.
- If the build fails, the leftover index is `indisvalid = false`. It is invisible to the planner but fully maintained by every write -- it is strictly worse than having no index, and must be dropped rather than left in place 'in case it is useful'.
- `CREATE INDEX CONCURRENTLY` is not restartable. A failed build must be cleaned up and started again from the beginning; there is no resume.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If the build is stalled on a specific backend, have the owning team close that session through their application -- that single action releases the build to continue.
- If reader lag has become customer-visible, cancel the build at the session level and clean up the INVALID index afterwards. Lag affecting customers outranks an index improvement every time.
- If the build failed with a transaction-block error, no cleanup is needed -- nothing was created. Re-run outside a transaction.

**Short-term remediation** (hours to days):

- Drop the INVALID index left by a failed build before retrying, using the failed-index-build workflow.
- Set `idle_in_transaction_session_timeout` so a leaked connection cannot stall the next build the same way.
- Raise `maintenance_work_mem` for the build session so the sort stays in memory and the build finishes faster, shortening the window in which it can be disrupted.
- Schedule builds for the lowest-traffic window available, not because the build blocks writes (it does not) but because it minimizes the number of concurrent transactions it must wait for.

**Long-term engineering fix** (days to weeks):

- Make long-running and idle-in-transaction sessions a monitored, alerted condition -- they cause far more than index build stalls.
- Configure deployment pipelines to run index migrations outside transactions by default, so the transaction-block failure stops recurring.
- Adopt per-partition concurrent builds for partitioned tables so no single build has to span the whole dataset.
- Record actual build durations per table size so future change tickets carry a realistic estimate rather than a guess.

## 10. Production Safety

- All `.sql` scripts here are read-only and safe to run repeatedly during a build -- monitoring frequently is encouraged.
- `CREATE INDEX CONCURRENTLY` must never be wrapped in `BEGIN`/`COMMIT`, and migration frameworks that open an implicit transaction must be configured not to for this statement.
- Cancelling a concurrent build is safe for the database but always leaves an INVALID index behind. Plan the cleanup as part of the change, not as an afterthought.
- Do not run two concurrent builds against the same table simultaneously -- their `ShareUpdateExclusiveLock` requests conflict and the second will simply wait.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- The build is stalled on a backend owned by a team that cannot be reached, and the stall is now blocking autovacuum on a high-write table.
- Reader lag caused by the build is affecting customer-facing reads -- treat as an incident and cancel the build.
- The build has failed more than once for reasons that are not understood -- stop retrying and investigate properly through failed-index-build.
- An Aurora failover occurred mid-build; confirm the state of the index on the new writer before any retry.

## 12. Related Issues

- [safe-index-creation](../safe-index-creation/README.md)
- [failed-index-build](../failed-index-build/README.md)
- [add-index-large-table](../add-index-large-table/README.md)
- [ddl-lock-investigation](../ddl-lock-investigation/README.md)
- [long-running-transactions](../../concurrency-and-locking/long-running-transactions/README.md)
- [idle-in-transaction](../../concurrency-and-locking/idle-in-transaction/README.md)
- [invalid-indexes](../../tables-and-indexes/invalid-indexes/README.md)
