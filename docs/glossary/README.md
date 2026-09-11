# Glossary

Terminology used across workflow READMEs and script `HOW TO INTERPRET
RESULTS` sections. Entries specific to Aurora (rather than community
PostgreSQL) are marked **[Aurora]**.

## A

* **Autovacuum** -- The background process that automatically runs
  `VACUUM` and `ANALYZE` on tables as they accumulate dead tuples or stale
  statistics, per table thresholds derived from `autovacuum_vacuum_scale_factor`
  / `autovacuum_analyze_scale_factor` and related settings.
* **Autovacuum worker** -- One of a limited pool of background processes
  (`autovacuum_max_workers`) that execute autovacuum's work; a busy
  cluster can have all workers occupied, delaying vacuum on other tables.

## B

* **Backend** -- A PostgreSQL server process handling one client
  connection; one row in `pg_stat_activity` per backend.
* **Bloat (table/index)** -- Space occupied by dead/obsolete row versions
  or index entries that have not yet been reclaimed by vacuum, inflating
  on-disk size relative to live data.
* **Buffer cache / `shared_buffers`** -- The in-memory cache of data
  pages; a "cold" cache means recent reads are not yet cached, increasing
  storage I/O and latency.

## C

* **Checkpoint** -- The point at which all dirty buffers are flushed to
  ensure durability up to that point; frequent/large checkpoints can cause
  I/O spikes.
* **Cluster endpoint** -- The Aurora DNS endpoint that always resolves to
  the current writer instance. **[Aurora]**
* **Cluster volume** -- Aurora's shared, distributed storage layer used
  by every instance in the cluster. **[Aurora]**
* **Connection pooling** -- Reusing a smaller number of physical database
  connections across many logical application requests (e.g., via
  PgBouncer or RDS Proxy) to avoid connection-count exhaustion.

## D

* **Deadlock** -- Two or more transactions each waiting on a lock held by
  the other, with no way to proceed; PostgreSQL detects and resolves these
  automatically by aborting one transaction.
* **Dead tuple** -- A row version made obsolete by an `UPDATE` or `DELETE`
  that has not yet been reclaimed by vacuum.

## F

* **Failover** -- Promoting a reader instance to become the new writer,
  typically after the previous writer becomes unavailable or as a planned
  operation. **[Aurora]**
* **Freeze / `relfrozenxid`** -- The process (and resulting marker) of
  marking old row versions as "frozen" so their transaction ID no longer
  needs comparison, preventing transaction ID wraparound.

## I

* **Idle in transaction** -- A session that has an open transaction
  (`BEGIN` issued) but is not currently executing a statement; long
  idle-in-transaction sessions hold back vacuum cleanup and can hold locks.
* **IOPS** -- I/O operations per second; a key capacity dimension for
  storage-bound workloads.

## L

* **Lock mode** -- The specific type of lock PostgreSQL takes for an
  operation (e.g., `ACCESS SHARE`, `ROW EXCLUSIVE`, `ACCESS EXCLUSIVE`),
  determining what other lock modes it conflicts with.
* **Lock contention** -- Multiple sessions competing for locks on the same
  object, causing some to wait.

## M

* **Multixact / Multixact ID** -- An identifier representing a set of
  transaction IDs jointly holding a row lock (e.g., from `SELECT ... FOR
  SHARE` by multiple transactions); can also approach wraparound and
  requires its own freezing.

## O

* **OLTP** -- Online transaction processing; short, frequent, latency-
  sensitive read/write transactions, characteristic of the trading/wallet/
  ledger workloads this repository targets.

## P

* **Performance Insights** -- An AWS monitoring feature providing a
  Database Load (`DBLoad`) metric decomposed by wait event and top SQL,
  without requiring direct SQL access. **[Aurora/RDS]**
* **Prepared transaction** -- A transaction that has completed
  `PREPARE TRANSACTION` (two-phase commit) but not yet `COMMIT PREPARED` /
  `ROLLBACK PREPARED`; holds locks and blocks vacuum cleanup until
  resolved.

## Q

* **Query plan regression** -- A change in the execution plan chosen by
  the planner for a previously well-performing query, usually due to
  changed statistics, data volume, or a configuration/version change,
  resulting in worse performance.

## R

* **RCA (Root Cause Analysis)** -- The process of tracing an observed
  symptom back to its underlying cause, as opposed to only treating the
  symptom.
* **Reader endpoint** -- The Aurora DNS endpoint that load-balances
  connections across available reader instances. **[Aurora]**
* **Replica lag** -- The delay between a change being durable on the
  writer and being visible/applied on a reader; on Aurora, reported in
  milliseconds via `aurora_replica_status()`. **[Aurora]**
* **`rds_superuser`** -- The most privileged role available on Aurora/RDS
  PostgreSQL; not equivalent to community PostgreSQL superuser. **[Aurora]**
* **RPO / RTO** -- Recovery Point Objective (how much data loss is
  tolerable) and Recovery Time Objective (how long recovery may take);
  key inputs to `disaster-recovery/` workflows.

## S

* **Sequential scan** -- A full table scan (`Seq Scan` in an execution
  plan), as opposed to an index scan; not inherently bad, but often a
  signal of a missing or unusable index for a selective query.
* **Sort spill** -- A sort operation exceeding `work_mem` and spilling
  intermediate data to temporary files on disk, visible in
  `EXPLAIN (ANALYZE, BUFFERS)` output and `pg_stat_database.temp_files`.

## T

* **Transaction ID (XID) wraparound** -- The finite, cyclical nature of
  PostgreSQL's 32-bit transaction ID counter; if old transaction IDs are
  not frozen in time, the counter wrapping around would make old data
  appear to be from the future, which PostgreSQL prevents by forcing
  aggressive autovacuum and, ultimately, refusing new writes.

## V

* **Vacuum** -- Reclaims space from dead tuples and updates visibility
  information; does not shrink the file on disk (see `VACUUM FULL`).
* **`VACUUM FULL`** -- Rewrites the entire table into a new, compact file,
  reclaiming disk space, but requires an `ACCESS EXCLUSIVE` lock for the
  duration.

## W

* **WAL (Write-Ahead Log)** -- The durability log of changes; on Aurora,
  WAL-equivalent redo records are shipped to the distributed storage
  layer rather than archived as local files in the traditional sense.
* **Wait event** -- The specific resource or condition a backend is
  currently waiting on (lock, I/O, client, extension-specific), visible in
  `pg_stat_activity.wait_event_type` / `wait_event`.
* **Writer instance** -- The single instance in an Aurora cluster that
  accepts write traffic at any given time. **[Aurora]**

## Related reading

* `docs/architecture/README.md` and `docs/aurora-postgresql/README.md` --
  fuller explanations of the Aurora-specific terms above.
* `docs/investigation-methodology/README.md` -- how these terms are used
  together across a typical investigation.
