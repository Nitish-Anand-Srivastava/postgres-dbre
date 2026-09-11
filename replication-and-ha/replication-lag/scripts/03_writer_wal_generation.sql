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
-- ever referencing pg_stat_wal, using a safe, catalog-only check (the
-- presence of the Aurora-specific aurora_version() function) so the
-- unsupported view/function is never resolved on the Aurora execution
-- path -- this is a plain catalog lookup on pg_proc, not a call to
-- aurora_version() itself, so it never fails on non-Aurora PostgreSQL
-- either.
SELECT EXISTS (
    SELECT 1 FROM pg_proc WHERE proname = 'aurora_version'
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
