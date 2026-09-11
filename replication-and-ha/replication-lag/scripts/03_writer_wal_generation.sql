/*
===============================================================================
SCRIPT NAME:
03_writer_wal_generation.sql

PURPOSE:
Checks current WAL generation rate on the writer, the primary driver of reader apply lag under high write volume.

AURORA POSTGRESQL VERSION:
Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise)

EXECUTION LOCATION:
Writer instance only (the query reads/writes state that only exists or is meaningful on the writer)

SAFETY:
READ ONLY

EXPECTED IMPACT:
Minimal -- reads system catalogs/statistics views only, no table locks beyond a brief catalog lookup.

REQUIRED PRIVILEGES:
Role membership in `pg_monitor` (or `pg_read_all_stats`) is sufficient. No superuser required.

PREREQUISITES:
None beyond CONNECT on the target database.

EXECUTION ORDER:
Step 03 of workflow 'replication-and-ha/replication-lag'

RELATED SCRIPTS:
04_reader_side_long_queries.sql

HOW TO INTERPRET RESULTS:
On Aurora PostgreSQL (verified through 17.7) this returns a single NOT AVAILABLE / guidance row instead of querying pg_stat_wal, since Aurora does not implement the pg_stat_get_wal() function backing that view -- use the CloudWatch or Performance Insights metrics named in the guidance row instead. On standard/self-managed PostgreSQL, compare wal_bytes across two snapshots to compute a rate; a high sustained WAL generation rate is the most common root cause of elevated reader apply lag.
===============================================================================
*/

-- Cluster-wide WAL generation statistics since the last stats reset
-- (pg_stat_wal, added in PostgreSQL 14 and unchanged in structure in 17).
-- Sustained high wal_bytes correlates directly with Aurora storage I/O and
-- with replica apply lag; compare two snapshots over a known time window to
-- get a WAL bytes/sec rate.
--
-- IMPORTANT (verified against Aurora PostgreSQL 17.7): pg_stat_wal is
-- present in the catalog on Aurora, but SELECTing it invokes the
-- underlying pg_stat_get_wal() function, which Aurora PostgreSQL does not
-- implement -- it raises "function pg_stat_get_wal() does not exist" even
-- though standard community PostgreSQL 17 supports it. Aurora does not
-- expose engine-internal WAL generation counters through this view at all
-- (WAL/redo generation happens against Aurora's distributed storage layer,
-- not local disk, so the community WAL-writer statistics this view
-- describes do not map onto Aurora's architecture). Detect Aurora *before*
-- ever sending a statement that references pg_stat_wal, so the
-- unsupported view/function is never parsed/resolved on the Aurora
-- execution path at all.
--
-- The detection below is a plain data-level check, never a call to an
-- Aurora-only function itself (so nothing here can fail on non-Aurora
-- PostgreSQL either): current_setting(name, missing_ok) is a stable core
-- PostgreSQL function that returns NULL instead of raising when the named
-- GUC does not exist, so it is safe to probe Aurora-only parameters with
-- it on any engine. Three independent Aurora signals are OR'd together so
-- a single naming/version quirk in one signal cannot cause a false
-- negative that would fall through to the unsupported pg_stat_wal branch:
--   1. the `aurora_version` GUC, which only exists on Aurora PostgreSQL
--      (visible via `SHOW aurora_version;` on a real Aurora instance);
--   2. the `rds.extensions` GUC, present on every RDS/Aurora PostgreSQL
--      instance (never on self-managed/community PostgreSQL);
--   3. the presence of the Aurora-specific aurora_version() SQL function
--      in pg_proc (checked by name only -- a catalog lookup, not a call).
SELECT (
    current_setting('aurora_version', true) IS NOT NULL
    OR current_setting('rds.extensions', true) IS NOT NULL
    OR EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'aurora_version')
)                                                                AS is_aurora
\gset

\if :is_aurora
SELECT
    'NOT AVAILABLE on Aurora PostgreSQL'::text                    AS status,
    'pg_stat_wal reports community PostgreSQL WAL-writer statistics that '
    'rely on pg_stat_get_wal(), which Aurora PostgreSQL (verified through '
    '17.7) does not implement -- querying pg_stat_wal here raises '
    '"function pg_stat_get_wal() does not exist". Aurora''s WAL/redo '
    'generation is written directly to the distributed storage layer, not '
    'local disk, so use the CloudWatch VolumeWriteIOPs / '
    'VolumeBytesUsed / WriteThroughput metrics, or the Performance '
    'Insights wait-event breakdown (wal_write / wal_sync / Log wait '
    'events), as the Aurora-native source for write/WAL volume instead.'
                                                                   AS guidance;
\else
SELECT
    wal_records,
    wal_fpi,
    pg_size_pretty(wal_bytes)                                    AS total_wal_bytes,
    wal_buffers_full,
    wal_write,
    wal_sync,
    round(wal_write_time::numeric, 2)                             AS wal_write_time_ms,
    round(wal_sync_time::numeric, 2)                              AS wal_sync_time_ms,
    stats_reset
FROM pg_stat_wal;
\endif
