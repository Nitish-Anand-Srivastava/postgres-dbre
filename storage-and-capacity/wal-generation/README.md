# WAL Generation Investigation

**Category:** Storage and Capacity | **Workflow:** `storage-and-capacity/wal-generation`

## 1. Problem Description

Write-ahead log generation is the hidden multiplier behind almost every Aurora storage and replication problem: the volume of redo a workload produces determines storage I/O cost, reader apply lag, checkpoint pressure, and how much space a lagging replication slot can pin. This workflow measures how much WAL the cluster is producing and attributes it to specific tables and statements. It opens with an important Aurora caveat -- the community `pg_stat_wal` view is not implemented on Aurora PostgreSQL -- and then works around it using per-table write volume, checkpoint behavior, and `pg_stat_statements`, backed by CloudWatch for the authoritative cluster-level numbers.

## 2. Typical Symptoms

- Aurora reader instances show rising `AuroraReplicaLag` during periods of heavy writing, even though reader CPU is low.
- CloudWatch `VolumeWriteIOPs` and `WriteThroughput` are climbing faster than the transaction rate.
- Storage I/O charges on the AWS bill are growing out of proportion to data volume.
- Checkpoints are frequently forced (requested) rather than timed, indicating WAL is filling `max_wal_size` faster than the checkpoint interval.
- A logical replication slot or AWS DMS task is falling behind and retaining a growing amount of WAL.
- A batch job (settlement, reconciliation, end-of-day mark-to-market) reliably causes a lag spike on every reader while it runs.

## 3. Business Impact

- Reader lag means stale data on any read path routed to a reader -- balance displays, order history, and reporting can show a customer state that is seconds behind reality, which is both a support burden and a trust problem on an exchange.
- Aurora bills storage I/O per request; excessive WAL generation is a direct, ongoing cash cost independent of stored bytes.
- High WAL volume lengthens crash recovery and failover, extending the exchange's effective downtime during an incident.
- A replication slot pinned behind a WAL flood can retain enough log to threaten cluster storage, which escalates from a performance issue to an availability issue.

## 4. Possible Root Causes

- Volume: genuine high write throughput -- order placement, fills, and ledger postings during a market event.
- Write amplification: over-indexing, where every insert writes one heap tuple and N index entries, each of which is WAL-logged.
- Write amplification: non-HOT updates caused by an index on a frequently-updated column, turning a cheap in-page update into a full row-plus-all-indexes rewrite.
- Full page writes: the first modification of a page after each checkpoint writes the entire page to WAL, so frequent checkpoints multiply WAL volume dramatically.
- Checkpoint tuning: `max_wal_size` too small for the write rate, forcing requested checkpoints and therefore more full-page-write bursts.
- Batch patterns: large single-transaction bulk operations (a full-table `UPDATE`, a mass backfill, an unbatched purge) generating a burst of WAL that readers must apply serially.
- Maintenance: index builds, `VACUUM FULL`, and table rewrites generating enormous WAL volumes in a short window.
- Bloat churn: a heavily bloated table generating far more page modifications than the logical change rate would suggest.

## 5. Investigation Strategy

1. Confirm which instance you are connected to and whether the community WAL statistics view is available at all -- on Aurora it is not, and knowing that up front prevents chasing a dead end.
2. Read checkpoint statistics, since forced checkpoints and full-page-write amplification are the most common tunable cause.
3. Capture the WAL-related configuration and the current WAL position, taking two samples a known interval apart to derive a real bytes-per-second rate.
4. Attribute WAL to statements using `pg_stat_statements`, noting the Aurora reporting caveat for its WAL columns.
5. Attribute WAL to tables using per-table write volume and HOT update ratios, which are reliable on Aurora where the WAL view is not.
6. Check replication slots for retained WAL, since a stalled consumer converts a transient WAL spike into persistent storage consumption.

## 6. Prerequisites

- `pg_monitor` role membership (or `pg_read_all_stats`).
- `pg_stat_statements` installed for the statement-level attribution script; it is never created by these scripts.
- CloudWatch access for `VolumeWriteIOPs`, `WriteThroughput`, and `AuroraReplicaLag` -- on Aurora these are the authoritative WAL-volume signals, not any SQL view.
- The writer endpoint for the WAL position script; WAL position functions cannot be called on an instance in recovery.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_cluster_wal_activity.sql`](scripts/01_cluster_wal_activity.sql) -- Reports cluster-wide WAL generation counters, detecting up front whether this engine exposes them at all.
2. [`scripts/02_checkpoint_activity.sql`](scripts/02_checkpoint_activity.sql) -- Reports checkpoint frequency and the forced-versus-timed split, the most common tunable cause of WAL amplification.
3. [`scripts/03_wal_settings_and_position.sql`](scripts/03_wal_settings_and_position.sql) -- Captures WAL-related configuration and the instance's current WAL position so a real generation rate can be derived from two samples.
4. [`scripts/04_wal_heavy_statements.sql`](scripts/04_wal_heavy_statements.sql) -- Attributes WAL generation to individual statements using pg_stat_statements, with the Aurora reporting caveat applied.
5. [`scripts/05_write_volume_by_table.sql`](scripts/05_write_volume_by_table.sql) -- Attributes write volume to individual tables, which is the reliable WAL proxy on Aurora where the WAL statistics view is unavailable.
6. [`scripts/06_replication_slot_wal_retention.sql`](scripts/06_replication_slot_wal_retention.sql) -- Identifies replication slots retaining WAL, which converts a transient write burst into persistent storage consumption.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- `pg_stat_wal` exists in the Aurora catalog but cannot be selected: the underlying `pg_stat_get_wal()` function is not implemented, and querying the view raises an error. This is by design -- Aurora writes redo to its distributed storage layer rather than to local WAL segments, so the community WAL-writer counters have no meaning. The first script in this workflow detects Aurora before ever touching the view.
- On Aurora, the authoritative WAL-volume signals are CloudWatch `VolumeWriteIOPs`, `WriteThroughput`, and `WriteIOPS`, plus the Performance Insights wait-event breakdown. No SQL view substitutes for them.
- Aurora readers do not replay a WAL stream from the writer the way a standard physical standby does; they read redo from the shared storage volume. WAL volume still drives reader lag, but `pg_stat_replication` will not show Aurora readers at all -- only genuine streaming consumers such as logical subscribers or DMS tasks.
- `full_page_writes` cannot be disabled on Aurora and should not be reasoned about as a tuning lever; reduce full-page-write volume by reducing checkpoint frequency (a larger `max_wal_size`) instead.

## 8. Interpretation Guide

- If the WAL activity script reports that `pg_stat_wal` is unavailable, that is the expected and correct result on Aurora PostgreSQL -- not an error and not a permissions problem. Aurora writes redo directly to its distributed storage layer rather than to local WAL segments, so the community WAL-writer counters have nothing to report. Use CloudWatch and the per-table/per-statement attribution scripts instead.
- A `pct_forced_checkpoints` above roughly 10% means `max_wal_size` is too small for the write rate. This matters far more than it sounds: each checkpoint restarts the full-page-write cycle, so frequent checkpoints multiply total WAL volume rather than merely rescheduling it.
- Take two samples of the WAL position script several minutes apart and difference them to get bytes per second. A single sample tells you almost nothing; the rate is the whole point.
- In `pg_stat_statements`, a `wal_bytes` of 0 for a statement you know performs writes means the instrumentation did not observe it on this engine version -- it is not evidence the statement is WAL-cheap. Corroborate with per-table write counters before concluding anything.
- A table with high `n_tup_upd` and a low `pct_hot_updates` is generating far more WAL per logical change than necessary. This is usually the single largest addressable source of WAL amplification and the fix (dropping an index on the updated column, or lowering fillfactor) is cheap relative to the benefit.
- A replication slot with a large `retained_wal` and `active = false` is an abandoned consumer. It pins WAL indefinitely and will keep doing so until the slot is dropped -- this is one of the few storage problems that genuinely gets worse the longer you leave it.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If a single batch job is flooding WAL and readers are lagging badly, pause or throttle that job -- this is the fastest lever available and has no lasting side effects.
- If an inactive replication slot is retaining a dangerous amount of WAL and its consumer is confirmed dead, drop the slot. Confirm with the owning team first: dropping an active consumer's slot forces a full resynchronization.
- Do not start an index build, bulk backfill, or table rewrite while WAL generation is already elevated and readers are lagging.

**Short-term remediation** (hours to days):

- Increase `max_wal_size` in the Aurora cluster parameter group to reduce forced checkpoints, which reduces full-page-write amplification.
- Batch large write operations into small committed chunks rather than single large transactions, so WAL is produced as a steady stream readers can keep up with.
- Drop unused and duplicate indexes on the highest-write tables -- each one removed is a WAL entry removed from every single insert and non-HOT update on that table.
- Reschedule heavy batch jobs (settlement, reconciliation, reporting extracts) outside peak trading hours so WAL bursts do not coincide with peak read traffic on the readers.

**Long-term engineering fix** (days to weeks):

- Lower `fillfactor` on update-heavy tables so more updates take the HOT path and skip index maintenance entirely.
- Partition large time-series tables so that retention is a metadata-only detach rather than a `DELETE` that generates WAL proportional to the data removed.
- Review the index set on every high-write table against its actual queries, and make write amplification an explicit consideration in index review.
- Move analytics and reporting workloads that drive large temporary write activity off the OLTP cluster entirely.
- Build WAL rate and replica lag into capacity dashboards so a step change is noticed immediately rather than at the next bill.

## 10. Production Safety

- All scripts in this workflow are read-only.
- The WAL position script calls `pg_current_wal_lsn()`, which raises an error on an instance in recovery; it detects recovery state first and takes a reader-safe branch instead, so it is safe to run anywhere.
- The replication slot script also reads the current WAL position and is therefore writer-only in practice -- run it against the cluster writer endpoint.
- Never drop a replication slot to reclaim WAL without confirming the consumer is genuinely dead. Dropping a live slot forces the consumer into a full resynchronization, which is a far larger event than the storage it frees.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Reader lag is high enough that reads are returning materially stale balances or order states to customers -- this is a customer-facing correctness issue and should be treated as an incident.
- A replication slot is retaining enough WAL to threaten cluster storage and the consumer cannot be contacted or recovered -- escalate for an authoritative decision to drop it.
- WAL generation has stepped up sharply with no deployment, no volume change, and no identifiable batch job -- investigate as unexpected-storage-growth and involve application engineering.
- CloudWatch shows write I/O rising while every in-database write counter is flat -- that discrepancy is not explainable from inside the database and needs an AWS support case.

## 12. Related Issues

- [unexpected-storage-growth](../unexpected-storage-growth/README.md)
- [database-growth](../database-growth/README.md)
- [capacity-forecasting](../capacity-forecasting/README.md)
- [replication-lag](../../replication-and-ha/replication-lag/README.md)
- [reader-lag-investigation](../../replication-and-ha/reader-lag-investigation/README.md)
- [high-iops](../../performance/high-iops/README.md)
- [unused-indexes](../../tables-and-indexes/unused-indexes/README.md)
