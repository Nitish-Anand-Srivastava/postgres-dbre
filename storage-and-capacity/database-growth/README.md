# Database Growth Investigation

**Category:** Storage and Capacity | **Workflow:** `storage-and-capacity/database-growth`

## 1. Problem Description

The cluster volume is growing and someone needs to say -- with evidence, not intuition -- which database, schema, and set of relations is responsible. This is the top-down entry point for the whole storage category: it walks from cluster volume down through per-database size, per-schema size, per-relation size, and object counts, so that by the end you can name the handful of objects driving the trend and hand off to the narrower workflow that owns the fix. On an exchange platform the answer is almost always a small number of append-only relations -- the trade tape, the double-entry ledger, order-book snapshots, or an audit/compliance log -- that have no retention policy attached to them.

## 2. Typical Symptoms

- CloudWatch `VolumeBytesUsed` for the Aurora cluster is trending up steadily with no corresponding increase in customer or order volume.
- `FreeLocalStorage` on individual instances is falling (this is local scratch space for sorts and temp tables, not the cluster volume -- a different problem, but frequently reported together).
- The monthly AWS bill line for Aurora storage and storage I/O is rising faster than trading volume.
- `pg_database_size()` for the primary application database has grown materially since the last capacity review.
- A backup, `pg_dump`, logical replication initial sync, or clone operation now takes noticeably longer than it did a quarter ago.

## 3. Business Impact

- Aurora storage is billed on the high-water mark of allocated volume and never shrinks -- an unmanaged growth trend is a permanent, compounding cost increase, not a temporary one.
- Larger relations mean longer vacuum cycles, longer index builds, and longer restore/clone times, which directly extends the recovery time objective for the exchange during an incident.
- Snapshot and export durations grow with volume size, eroding the margin in the nightly regulatory reporting and reconciliation windows.
- Once growth is driven by a genuinely business-critical table (the ledger), the remediation options are slow and risky (partitioning, archival migrations) -- so catching the trend early is worth far more than reacting to it late.

## 4. Possible Root Causes

- Retention: append-only history (trades, ledger_entries, order_book_snapshots, audit logs, webhook/callback logs) written forever with no retention or archival policy.
- Retention: soft-delete patterns where rows are flagged `deleted_at` rather than removed, so the table only ever grows.
- Bloat: dead tuples not being reclaimed because autovacuum is not keeping up, or because a long-running transaction or stale replication slot is holding back the xmin horizon.
- Indexing: over-indexing on wide, write-heavy tables -- index bytes frequently exceed heap bytes on an over-indexed order table.
- Schema design: wide JSON/JSONB payload columns (raw exchange API responses, blockchain transaction bodies) that TOAST heavily and are never pruned.
- Schema design: a partitioned table whose maintenance job creates new partitions but never detaches/archives old ones, accumulating both data and catalog entries.
- Workload: a genuine, expected increase in trading volume -- which is a capacity-planning outcome, not a defect, but must still be forecast and budgeted.
- Operational: an abandoned migration leaving a full backup copy of a large table (`orders_old`, `trades_backup_2024`) behind indefinitely.

## 5. Investigation Strategy

1. Establish the cluster-level picture first from CloudWatch (`VolumeBytesUsed`), because PostgreSQL cannot see the Aurora volume -- SQL only sees logical object size.
2. Rank databases by size to confirm which database the growth lives in before drilling further.
3. Rank user schemas within that database to attribute growth to a business domain (trading path, money path, audit/compliance).
4. Rank individual relations by total size, then break the largest ones into heap / TOAST / index components -- the component split determines which remediation applies.
5. Rank indexes separately: over-indexing is a common and easily reversible cause that is invisible when looking only at total relation size.
6. Count objects per schema to detect partition sprawl and catalog inflation, which do not show up as bytes in the top-N relation list.
7. Finally, if a size-history collector has been deployed, compute actual growth rates over the retention window rather than reasoning from a single snapshot.

## 6. Prerequisites

- `pg_monitor` role membership (or `pg_read_all_stats`) and `CONNECT` on each database you want to size.
- Read access to the AWS Console or CloudWatch for `VolumeBytesUsed` -- the true Aurora storage figure is not available from SQL at all.
- Optionally, the `dba_toolkit.table_size_history` collector (see the growth-monitoring automation) for genuine growth-rate rather than point-in-time data.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_database_sizes.sql`](scripts/01_database_sizes.sql) -- Ranks every connectable database in the cluster by logical size to confirm which database the growth actually lives in.
2. [`scripts/02_schema_size_breakdown.sql`](scripts/02_schema_size_breakdown.sql) -- Attributes the current database's footprint to individual user schemas so growth can be assigned to a business domain and an owning team.
3. [`scripts/03_largest_tables.sql`](scripts/03_largest_tables.sql) -- Ranks individual relations by total size (heap plus indexes plus TOAST) -- the definitive list of what is consuming the volume.
4. [`scripts/04_table_size_components.sql`](scripts/04_table_size_components.sql) -- Splits each large relation into heap, TOAST, and index bytes, because the component mix determines which remediation is actually available.
5. [`scripts/05_largest_indexes.sql`](scripts/05_largest_indexes.sql) -- Ranks individual indexes by size so that over-indexing is visible independently of the tables that own the indexes.
6. [`scripts/06_object_counts_and_growth_history.sql`](scripts/06_object_counts_and_growth_history.sql) -- Counts objects per schema to expose partition sprawl, then reports measured growth over time if the size-history collector has been deployed.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- The Aurora cluster volume grows automatically in 10 GiB increments and is never reduced by deleting data. A 2 TB volume that is logically emptied to 200 GB is still a 2 TB volume for billing purposes; the only way to reclaim it is to create a new cluster (snapshot restore, or a logical dump/restore) and cut over.
- `pg_database_size()` measures logical PostgreSQL object size only. It has no visibility into the Aurora storage layer, does not include WAL, and cannot be reconciled exactly against `VolumeBytesUsed`. Always quote CloudWatch, not SQL, when discussing billed storage.
- Aurora storage is shared across the writer and all readers -- adding readers does not multiply storage, which is why reader-heavy fanout is cheap on Aurora compared with self-managed replicas.
- `FreeLocalStorage` is a completely separate, per-instance resource used for temporary files and local scratch. Filling it up will fail queries even when the cluster volume has plenty of room -- see the temp-file-growth workflow, not this one.
- Aurora backups and snapshots are incremental against the storage layer and do not consume additional space proportional to logical size, so backup storage is not a useful proxy for database growth.

## 8. Interpretation Guide

- The sum of `pg_database_size()` across all databases will be *smaller* than CloudWatch `VolumeBytesUsed`. That gap is normal and is made up of WAL, temporary space, the free space map, and -- most importantly -- previously-allocated volume that Aurora never released after deletes. A large and growing gap is itself a finding: it means space is being freed logically but not recovered physically.
- If one schema accounts for more than roughly 60-70% of user data, the entire capacity conversation belongs to that schema's owning team; do not spread remediation effort evenly across schemas.
- When a relation's `pct_indexes` exceeds 50%, the cheapest available win is almost always index cleanup, not data archival -- it is reversible, needs no data migration, and also reduces write amplification and WAL volume.
- A high `pct_toast` points at wide varlena columns (JSON payloads, blobs). These compress well but are expensive to scan; consider whether the payload needs to live in the OLTP database at all, or belongs in object storage with only a reference retained.
- A very high `estimated_row_count` with a modest heap size means narrow rows and genuine volume -- that is a partitioning/archival conversation. A modest row count with a large heap means wide rows or bloat -- check dead tuples before assuming it is real data.
- A schema with thousands of objects but modest bytes is partition sprawl. The cost there is planning time, catalog size, and lock footprint rather than storage, and the fix is partition retention, not archival.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Nothing in this workflow requires an immediate action -- growth is a trend, not an outage. Resist the urge to run `VACUUM FULL` to 'get space back': it takes an `AccessExclusiveLock` for the duration, and on Aurora it does not return the freed space to the volume anyway.
- If free space on the cluster is genuinely close to the 128 TiB ceiling, or `FreeLocalStorage` on an instance is near zero, treat it as an incident and escalate to AWS support immediately rather than attempting a SQL-level fix.

**Short-term remediation** (hours to days):

- Drop confirmed-unused and duplicate indexes on the largest relations -- see the index-growth workflow here and the drop-index-safely runbook in schema-changes.
- Remove abandoned migration leftovers (`*_old`, `*_backup_*` copies of large tables) after confirming with the owning team, using the archival validation process rather than an ad-hoc DROP.
- Fix whatever is holding back the xmin horizon (idle-in-transaction sessions, inactive replication slots) so that autovacuum can actually reclaim space for reuse -- see the unexpected-storage-growth workflow.
- Attach a retention policy to the top one or two append-only relations, even a conservative one, so the trend stops compounding while the longer-term design work is scheduled.

**Long-term engineering fix** (days to weeks):

- Partition the largest time-series relations (trade tape, ledger, order-book snapshots) so that retention becomes a metadata-only `DETACH PARTITION` rather than a `DELETE` that generates bloat and WAL.
- Move cold history out of the OLTP cluster entirely -- S3/Parquet for analytics, a separate reporting store for compliance queries -- keeping only the hot window online.
- Move large opaque payloads (raw exchange API responses, blockchain transaction bodies) to object storage and keep only a key plus indexed metadata in PostgreSQL.
- Make retention a schema-design requirement: no new high-volume table ships without a documented retention/partitioning plan and an owner.
- Deploy the size-history collector and a capacity dashboard so growth is reviewed on a schedule rather than discovered from a bill.

## 10. Production Safety

- Every script in this workflow is read-only and safe to run at any time, including during an incident; they touch catalogs and statistics views only.
- `pg_total_relation_size()` over many thousands of relations involves one stat() per fork per relation and can take a few seconds on a database with heavy partition sprawl -- prefer running the top-N variants on the writer during a busy period rather than an unbounded scan.
- Do not run `VACUUM FULL`, `CLUSTER`, or `pg_repack` as a response to anything found here without going through the table-bloat workflow first; on Aurora they consume the volume's high-water mark twice and do not shrink billed storage.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Cluster volume growth is on a trajectory to reach the Aurora 128 TiB volume limit within the forecast horizon -- involve AWS support and database engineering leadership immediately.
- The largest and fastest-growing relation is the financial ledger, where no data may be deleted for regulatory reasons -- this needs a compliance-approved archival design, not a DBA-level fix.
- PostgreSQL-reported logical size is flat or falling while CloudWatch `VolumeBytesUsed` keeps climbing -- that pattern is not explainable from inside the database and needs an AWS support case.
- Growth rate has changed abruptly (a step change rather than a trend) with no corresponding deployment or volume event -- treat it as unexpected-storage-growth and investigate as a possible defect or runaway process.

## 12. Related Issues

- [table-growth](../table-growth/README.md)
- [index-growth](../index-growth/README.md)
- [capacity-forecasting](../capacity-forecasting/README.md)
- [unexpected-storage-growth](../unexpected-storage-growth/README.md)
- [large-tables](../../tables-and-indexes/large-tables/README.md)
- [investigate-partitioning-candidate](../../partitioning/investigate-partitioning-candidate/README.md)
- [investigate-archiving-candidate](../../archival-and-data-lifecycle/investigate-archiving-candidate/README.md)
