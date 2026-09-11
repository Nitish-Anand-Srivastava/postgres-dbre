# Unexpected Storage Growth

**Category:** Storage and Capacity | **Workflow:** `storage-and-capacity/unexpected-storage-growth`

## 1. Problem Description

Storage has jumped in a way the normal growth trend does not explain: a step change rather than a slope, or the Aurora volume climbing while logical database size stays flat. This is an incident-shaped investigation rather than a capacity-planning one, and its defining characteristic is that the obvious answer -- more data was inserted -- is usually wrong. The far more common causes are space that cannot be reclaimed (dead tuples pinned by a held-back xmin horizon, an abandoned replication slot retaining WAL, an orphaned transaction) and space consumed by something other than table data (a runaway index build, an unfinished migration copy, a flood of temporary files). The distinguishing question this workflow answers is: is space being consumed, or merely failing to be released?

## 2. Typical Symptoms

- CloudWatch `VolumeBytesUsed` steps up sharply within hours rather than trending, with no corresponding deployment or volume event.
- `pg_database_size()` is flat or falling while the Aurora volume keeps climbing.
- A purge or archival job completed successfully but freed no storage at all.
- Dead tuple counts on one or more large tables are high and refuse to fall despite autovacuum running.
- `FreeLocalStorage` on an instance is dropping independently of the cluster volume.
- An unfamiliar large relation has appeared near the top of the size rankings.
- Storage growth started at a precisely identifiable moment that correlates with a deployment, a failover, or a long-running batch job.

## 3. Business Impact

- Unexplained growth erodes capacity headroom without warning, removing the lead time that would otherwise allow a careful remediation.
- If the cause is a held-back xmin horizon, the same root cause is simultaneously preventing vacuum from freezing tuples -- which puts the cluster on the path to transaction ID wraparound, a far more serious availability event.
- An abandoned replication slot retaining WAL will keep growing indefinitely and can eventually threaten the cluster, so the problem strictly worsens with time.
- On Aurora the storage consumed by a transient event is never released, so even a fully resolved incident leaves a permanent cost increase behind.

## 4. Possible Root Causes

- Not released: a long-running transaction or idle-in-transaction session holding back the xmin horizon, so vacuum cannot remove dead tuples anywhere in the database.
- Not released: an inactive or lagging replication slot (a logical subscriber, an abandoned AWS DMS task) pinning both WAL and the xmin horizon.
- Not released: an orphaned prepared transaction, which holds locks and the xmin horizon indefinitely and survives restarts.
- Not released: autovacuum repeatedly cancelled by conflicting locks on a busy table, so dead tuples accumulate faster than they are reclaimed.
- Consumed: a bulk operation -- an unbatched `UPDATE` or `DELETE` across a large table -- creating one dead tuple per row touched plus a burst of WAL.
- Consumed: an index build or table rewrite in progress, which requires space for the new object alongside the old one.
- Consumed: a migration leftover, such as a full backup copy of a large table created 'temporarily' and never dropped.
- Consumed: a flood of temporary files from a spilling query, which consumes per-instance local storage rather than the cluster volume.
- Consumed: a partition maintenance job creating new partitions without detaching old ones, or creating far more partitions than intended.
- Consumed: a runaway application defect -- a retry loop inserting duplicates, a logging table with no retention, a webhook handler recording every payload.

## 5. Investigation Strategy

1. Establish first whether the growth is logical (visible in `pg_database_size()`) or purely at the Aurora volume level -- this single question splits the investigation in two.
2. Snapshot relation sizes and compare against the last recorded baseline to find what changed, looking specifically for relations that are new rather than merely large.
3. Check dead tuple accumulation, since 'space not released' is the most common cause and dead tuples are its fingerprint.
4. Hunt for anything holding back the xmin horizon: long-running transactions, idle-in-transaction sessions, prepared transactions.
5. Check replication slots for retained WAL and pinned xmin, which is the second most common cause and the one that worsens fastest.
6. Check temp file usage, which explains local storage growth that never appears in the cluster volume at all.
7. Check for in-progress index builds and for INVALID indexes left by builds that already failed.

## 6. Prerequisites

- `pg_monitor` role membership (or `pg_read_all_stats`).
- A previous size baseline to compare against -- from the size-history collector, a prior capacity review, or the database-growth workflow. Without a baseline, 'unexpected' cannot be distinguished from 'always been that way'.
- CloudWatch `VolumeBytesUsed` and `FreeLocalStorage` history covering the period in question, ideally at one-minute resolution so the step change can be timed precisely.
- A deployment and change timeline for the same period, so a correlation can be tested rather than guessed at.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_database_size_snapshot.sql`](scripts/01_database_size_snapshot.sql) -- Takes a current per-database size snapshot to determine whether the growth is logical at all, or purely at the Aurora volume level.
2. [`scripts/02_largest_tables_snapshot.sql`](scripts/02_largest_tables_snapshot.sql) -- Snapshots relation sizes so they can be compared against the previous baseline to find what actually changed.
3. [`scripts/03_dead_tuple_accumulation.sql`](scripts/03_dead_tuple_accumulation.sql) -- Quantifies dead tuples per table to test the most common hypothesis: that space is not being released rather than consumed.
4. [`scripts/04_xmin_horizon_holders.sql`](scripts/04_xmin_horizon_holders.sql) -- Finds long-running transactions, idle-in-transaction sessions, and prepared transactions that hold back the xmin horizon and block all reclamation.
5. [`scripts/05_replication_slot_retention.sql`](scripts/05_replication_slot_retention.sql) -- Checks replication slots for retained WAL and pinned xmin -- the cause that worsens fastest if left alone.
6. [`scripts/06_temp_file_and_local_storage.sql`](scripts/06_temp_file_and_local_storage.sql) -- Checks temporary file usage, which explains local storage growth that never appears in the cluster volume.
7. [`scripts/07_index_builds_and_invalid_indexes.sql`](scripts/07_index_builds_and_invalid_indexes.sql) -- Finds in-progress index builds consuming space right now, and INVALID indexes left behind by builds that already failed.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Aurora volume growth is permanent. Even a fully resolved transient event -- a one-off bulk update, a completed index build, a purge that generated millions of dead tuples -- leaves the high-water mark where it peaked. This is why speed of response matters more on Aurora than on a self-managed instance where space returns to the filesystem.
- Logical size flat while the volume climbs is the classic Aurora signature of WAL retention, temp file usage, or an in-progress build. It is not a PostgreSQL-visible phenomenon, which is exactly why the CloudWatch timeline is a mandatory input to this investigation.
- Aurora readers do not appear in `pg_stat_replication`, so a lagging reader is not a possible cause of retained WAL here. Only genuine streaming consumers -- logical replication subscribers, AWS DMS tasks -- can pin WAL through a slot.
- `FreeLocalStorage` dropping while `VolumeBytesUsed` is flat means the growth is temp files on one instance, not cluster data. Those are entirely different problems with entirely different fixes -- see the temp-file-growth workflow.
- Aurora's storage layer performs its own garbage collection asynchronously, so small timing discrepancies between a completed cleanup inside PostgreSQL and the CloudWatch metric are normal. A sustained divergence over hours is not.

## 8. Interpretation Guide

- Start with the split: if `pg_database_size()` grew in step with the volume, something was written and the investigation is about finding what. If logical size is flat while the volume climbed, space was consumed by something outside normal table data -- WAL retention, temp files, or an index build -- and the table-level scripts will find nothing.
- High dead tuples that persist across autovacuum cycles is the signature of 'space not released'. Do not tune autovacuum in response; find what is holding back the xmin horizon, because until that is cleared, no amount of vacuum effort can remove those tuples.
- A transaction open for hours -- especially one sitting `idle in transaction` -- pins the xmin horizon for the entire database, not just for the tables it touched. A single forgotten session in a developer's terminal or a connection-pool leak can block reclamation cluster-wide.
- A replication slot with `active = false` and large retained WAL is an abandoned consumer. It pins both WAL and, for a logical slot, the xmin horizon. This is the cause that most reliably gets worse the longer it is left, and the fix (dropping the slot) needs confirmation but not much deliberation.
- A prepared transaction that has been open for more than a few minutes is almost certainly orphaned -- a two-phase commit whose coordinator died. It holds locks and the xmin horizon indefinitely and survives instance restarts, so it will never resolve itself.
- An in-progress index build temporarily needs space for the new index alongside the existing data, and a build on a very large table can consume a surprising amount. This is expected and transient -- but on Aurora the volume high-water mark it creates is permanent.
- A new relation you do not recognize near the top of the size rankings, particularly one named like a copy (`orders_old`, `trades_backup`, `ledger_entries_new`), is a migration leftover until someone proves otherwise. Confirm ownership before proposing anything.
- If logical size is flat, dead tuples are normal, no slot is retaining WAL, and no build is running, yet the Aurora volume still climbed -- that is not explainable from inside the database and needs an AWS support case with the CloudWatch timeline attached.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- End whatever is holding back the xmin horizon: have the owning team close long-running or idle-in-transaction sessions through their application. This is the highest-value immediate action and it unblocks reclamation across the whole database.
- Roll back or commit an orphaned prepared transaction once its coordinator is confirmed dead -- it will never resolve on its own and blocks reclamation indefinitely.
- Drop an inactive replication slot whose consumer is confirmed dead, after checking with the owning team. Dropping a live consumer's slot forces a full resynchronization, so confirm before acting.
- Stop a runaway bulk operation or spilling query at the application layer if it is actively consuming storage right now.

**Short-term remediation** (hours to days):

- Once the xmin horizon is free, allow autovacuum to reclaim the dead tuples, or run a manual `VACUUM` (never `VACUUM FULL`) on the worst-affected tables during a quieter period.
- Drop confirmed migration leftovers and INVALID indexes after establishing ownership.
- Batch the operation that caused the burst -- a `DELETE` of millions of rows in one transaction creates millions of dead tuples at once and should have been chunked.
- Add monitoring for long-running transactions, idle-in-transaction sessions, and inactive replication slots so the same cause is detected in minutes rather than discovered as a storage step change.

**Long-term engineering fix** (days to weeks):

- Set `idle_in_transaction_session_timeout` on the cluster so a leaked connection cannot pin the xmin horizon indefinitely.
- Establish ownership and an expiry review for every replication slot, so abandoned consumers are found by process rather than by incident.
- Replace bulk `DELETE`-based purges with partition detach, which reclaims space as a metadata operation and creates no dead tuples at all.
- Add a cleanup step with an owner and a deadline to every migration runbook, so backup copies of large tables are removed rather than forgotten.
- Alert on the rate of change of `VolumeBytesUsed`, not just its level, so a step change pages someone the same day it happens.

## 10. Production Safety

- Every script in this workflow is read-only and safe to run during an active incident; they read catalogs and statistics views only.
- Do not reach for `VACUUM FULL` to recover space during an incident. It takes an `AccessExclusiveLock` for its entire duration, needs as much free space as the table it rewrites, and on Aurora returns nothing to the volume anyway.
- Never terminate a backend or drop a replication slot on the basis of these reports alone -- confirm ownership and impact first. Dropping an active consumer's slot is a far larger event than the storage it frees.
- The replication slot script reads the current WAL position and must therefore run against the writer.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- The Aurora volume is growing while every in-database metric is flat and no slot, build, or temp file activity explains it -- open an AWS support case with the CloudWatch timeline attached.
- The same root cause holding back the xmin horizon is also driving transaction age upward -- this is a wraparound risk and takes priority over the storage symptom entirely.
- An abandoned replication slot is retaining enough WAL to threaten cluster storage and its owner cannot be identified or contacted -- escalate for an authoritative decision to drop it.
- Growth is traced to an application defect actively writing unbounded data -- escalate to application engineering as a production incident, since every minute of delay is permanent Aurora storage.
- Remediation would require terminating sessions on the trading path, or dropping a relation whose ownership is unclear -- both need explicit authorization above the on-call DBA.

## 12. Related Issues

- [database-growth](../database-growth/README.md)
- [table-growth](../table-growth/README.md)
- [wal-generation](../wal-generation/README.md)
- [temp-file-growth](../temp-file-growth/README.md)
- [dead-tuples](../../vacuum-and-autovacuum/dead-tuples/README.md)
- [long-running-transactions](../../concurrency-and-locking/long-running-transactions/README.md)
- [idle-in-transaction](../../concurrency-and-locking/idle-in-transaction/README.md)
- [prepared-transactions](../../transactions-and-xid/prepared-transactions/README.md)
- [replication-health](../../replication-and-ha/replication-health/README.md)
