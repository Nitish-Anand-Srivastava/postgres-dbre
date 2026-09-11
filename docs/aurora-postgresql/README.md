# Aurora PostgreSQL: Differences From Community PostgreSQL

Every workflow in this repository targets **Amazon Aurora
PostgreSQL-Compatible Edition, engine version 17+**. Aurora is
wire-compatible with community PostgreSQL, but it is not operationally
identical. This page is the authoritative list of differences that scripts
and runbooks in this repository rely on or must avoid assuming away.

## 1. Things that behave differently

| Area | Community PostgreSQL | Aurora PostgreSQL |
| --- | --- | --- |
| Replication | Physical/logical streaming replication with WAL shipped over the network; lag measured by comparing `pg_stat_replication` / `pg_last_wal_replay_lsn()` | Storage-level log record replication to readers; lag measured in milliseconds via `aurora_replica_status()` |
| Crash recovery | Replays WAL from the last checkpoint on restart; can take minutes on a busy instance | Storage already holds durable redo records; recovery is fast and largely size-independent |
| Checkpoints | Directly tied to WAL segment recycling and crash-recovery time | Still occur and still matter for buffer flushing and some I/O smoothing, but are decoupled from local WAL retention in the traditional sense |
| `VACUUM FULL` / table rewrite locking | Exclusive lock, standard PostgreSQL locking behavior | Same locking behavior; still exclusive and blocking -- Aurora does not remove this cost |
| Read replicas | Each replica is an independent, fully replicated copy of the data directory | Readers share the same distributed storage volume as the writer; no separate physical copy of the data files |
| Superuser | Available on self-managed instances | Not available. The most-privileged role is `rds_superuser`, which excludes operations that would require host/OS access (e.g., filesystem access, `COPY` to a server-side file, loading arbitrary shared libraries) |
| Some extensions | Any extension buildable from source | Restricted to the AWS-curated, version-specific extension allow-list per engine version; `CREATE EXTENSION` fails for anything not on that list |
| Replication slots (physical) | Fully supported, commonly used for external consumers | Supported with caveats; unused/stale slots retain WAL on storage and are a common cause of unexpected storage growth in Aurora -- see `storage-and-capacity/` |
| `pg_stat_statements` | Optional but always installable | Available and commonly pre-loaded via the cluster parameter group's `shared_preload_libraries`, but must still be explicitly `CREATE EXTENSION`-ed per database |
| WAL generation statistics | `pg_stat_wal` (PostgreSQL 14+) and `pg_stat_statements`'s `wal_records` / `wal_fpi` / `wal_bytes` columns report actual WAL volume generated | Not supported / not populated through at least Aurora PostgreSQL 17.7 -- see the dedicated note below; do not use these as a WAL-volume source on Aurora |
| Enhanced Monitoring / Performance Insights | Not applicable (self-managed) | First-class, OS- and instance-level metrics available outside SQL; see `observability/` |
| Parameter changes | `postgresql.conf`, reload/restart per instance | Managed through **DB cluster parameter groups** (cluster-wide) and **DB instance parameter groups** (per-instance); some parameters require a reboot, some a failover |

## 2. Things you should not assume are available

* **Superuser-only functions and views** that require OS-level access (for
  example, functions that read arbitrary server-side files, or extensions
  that require `shared_preload_libraries` changes you cannot make without
  going through a parameter group and a reboot).
* **Arbitrary extensions.** Always check
  `SELECT * FROM pg_available_extensions` before assuming an extension can
  be installed; do not assume `pg_stat_kcache`, `pg_cron` (available on
  Aurora but must be explicitly enabled via parameter group first), or
  other third-party extensions are present without verifying.
* **Local filesystem access.** Scripts must not assume they can write to,
  or read from, the instance's local filesystem.
* **`pg_stat_replication` as the source of truth for reader lag.** It may
  return rows on Aurora but the semantics differ from upstream physical
  streaming replication; prefer `aurora_replica_status()` for authoritative
  Aurora reader lag figures (see `common/scripts/` for a safe example).
* **`pg_stat_wal` / `pg_stat_get_wal()` as a WAL-generation source.**
  Through at least Aurora PostgreSQL 17.7, this view (introduced in
  community PostgreSQL 14) is not supported / not populated in the same
  way as upstream -- Aurora's storage-level redo-log model does not feed
  the standard WAL-generation instrumentation that `pg_stat_wal` reads
  from. Do not treat it as a source of truth for WAL volume on Aurora.
  Likewise, `pg_stat_statements`'s `wal_records` / `wal_fpi` / `wal_bytes`
  columns are commonly observed reading **zero** for queries on Aurora
  even when the underlying operation clearly writes data. **Treat a zero
  reading from either source as "not observed by this instrumentation
  path," not as proof that no WAL was generated.** For WAL-volume
  investigation on Aurora, prefer storage/CloudWatch-level indicators
  (e.g. `VolumeWriteIOPs`, `VolumeBytesUsed` trend) over these two views
  -- see `observability/` and `storage-and-capacity/`.
* **Replica promotion timing guarantees.** Aurora failover is fast, but it
  is not synchronous with the application's perspective. Always validate
  connectivity and role (`pg_is_in_recovery()`) after a failover rather
  than assuming success from the control-plane event alone.

## 3. Aurora-specific functions used in this repository

These are documented AWS Aurora PostgreSQL functions (not community
PostgreSQL). Scripts that use them mark `AURORA POSTGRESQL VERSION` /
`PREREQUISITES` in their header accordingly.

| Function | Purpose |
| --- | --- |
| `aurora_version()` | Returns the Aurora PostgreSQL engine version string. |
| `aurora_db_instance_identifier()` | Returns the DB instance identifier of the instance you are currently connected to. |
| `aurora_replica_status()` | Returns per-instance replica status/lag for every instance in the cluster, including the writer. |
| `aurora_stat_dml_activity()` | Returns cumulative INSERT/UPDATE/DELETE counts observed at the storage layer. |

Full reference: see AWS's [Aurora PostgreSQL functions reference]
(https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Appendix.AuroraPostgreSQL.Functions.html).

## 4. Parameter groups

* **Cluster parameter group** -- applies to every instance in the cluster;
  used for cluster-wide settings such as `shared_preload_libraries`,
  `rds.logical_replication`, and most `wal_*` / replication-related
  settings.
* **Instance (DB) parameter group** -- applies to one instance; used for
  instance-scoped tuning such as `work_mem`, `random_page_cost`, or
  `log_min_duration_statement` overrides for a specific reader.
* Changing either can require a **reboot** (sometimes a **failover** for
  writer-affecting static parameters). Always check whether a parameter is
  `PENDING_REBOOT` before assuming a change is live -- `SHOW <param>;` in
  an active session may not reflect a pending parameter group change.

## 5. Version compatibility

This repository targets Aurora PostgreSQL 17+. Where a script depends on
behavior introduced in a specific 17.x point release or differs on 15/16,
that is called out explicitly in the script's own header
(`AURORA POSTGRESQL VERSION` field) rather than assumed silently.

## 6. Related reading

* `docs/architecture/README.md` -- the structural "why" behind these
  differences.
* `docs/prerequisites/README.md` -- what must be enabled/granted before
  running workflows that depend on the items above.
* `docs/production-safety/README.md` -- how "no superuser, no arbitrary
  extensions" translates into the safety rules every script follows.
