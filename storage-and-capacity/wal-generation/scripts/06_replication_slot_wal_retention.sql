/*
===============================================================================
SCRIPT NAME:
06_replication_slot_wal_retention.sql

PURPOSE:
Identifies replication slots retaining WAL, which converts a transient write burst into persistent storage consumption.

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
Step 06 of workflow 'storage-and-capacity/wal-generation'

RELATED SCRIPTS:
../../replication-and-ha/replication-health/README.md

HOW TO INTERPRET RESULTS:
Any slot with active = false and a large retained_wal is an abandoned consumer pinning storage indefinitely, and it will keep growing until the slot is dropped or the consumer returns. Slots with wal_status of 'extended' or 'lost' need immediate attention: 'lost' means required WAL has already been removed and the consumer can no longer resume without a full resynchronization. On Aurora, note that the cluster's own reader instances never appear here -- only genuine streaming consumers such as logical replication subscribers or AWS DMS tasks do. This script reads the current WAL position and therefore must run against the writer.
===============================================================================
*/

-- Combines replication slot lag with current WAL position to flag slots
-- that are retaining an unusually large amount of WAL. On Aurora, WAL
-- retained by an inactive or lagging logical replication slot still
-- consumes storage on the cluster volume and can eventually force
-- corrective action (dropping the slot) if the consumer cannot be
-- recovered.
--
-- IMPORTANT (verified against Aurora PostgreSQL 17.7): pg_current_wal_lsn()
-- is not available on Aurora -- detect Aurora first via a safe,
-- catalog/GUC-only check (never a call to an Aurora-only function itself,
-- so this never fails on non-Aurora PostgreSQL either) and never send a
-- statement referencing pg_current_wal_lsn() on the Aurora execution path
-- at all. On Aurora, per-slot retained WAL still cannot be sized from
-- SQL; report retention via wal_status instead (a slot already reports
-- 'lost'/'extended'/'unreserved' there) and point at CloudWatch/
-- aurora_replica_status() for volume-level WAL retention pressure.
\set retained_wal_warning_gb 50
SELECT (
    current_setting('aurora_version', true) IS NOT NULL
    OR current_setting('rds.extensions', true) IS NOT NULL
    OR EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'aurora_version')
)                                                                AS is_aurora
\gset

\if :is_aurora
SELECT
    slot_name,
    slot_type,
    active,
    wal_status,
    'NOT AVAILABLE on Aurora (see wal_status and the guidance column)'::text
                                                                  AS retained_wal,
    NULL::boolean                                                AS exceeds_warning_threshold,
    'pg_current_wal_lsn() is not available on Aurora PostgreSQL, so retained '
    'WAL cannot be sized in bytes from SQL here. A wal_status of ''lost'' or '
    '''extended'' already signals a slot that has fallen dangerously behind; '
    'use CloudWatch (VolumeBytesUsed trend, ReplicaLag) or '
    'aurora_replica_status() for cluster-wide storage-layer WAL retention '
    'pressure instead.'                                          AS guidance
FROM pg_replication_slots
ORDER BY slot_name;
\else
-- NOTE: the threshold is cast to numeric BEFORE multiplying by 1024^3.
-- pg_wal_lsn_diff() returns numeric, but the psql-substituted literal
-- ":retained_wal_warning_gb" is a bare integer constant; PostgreSQL infers
-- an int4 literal type for "50 * 1024 * 1024 * 1024" left-to-right before
-- ever comparing it against the numeric LSN diff, and that intermediate
-- product (~53.7 billion) overflows int4 (max ~2.1 billion), raising
-- "integer out of range" -- casting the threshold to numeric first forces
-- numeric arithmetic throughout and avoids the overflow entirely.
SELECT
    slot_name,
    slot_type,
    active,
    wal_status,
    pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS retained_wal,
    pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) >
        (:retained_wal_warning_gb::numeric * 1024 * 1024 * 1024)    AS exceeds_warning_threshold,
    NULL::text                                                      AS guidance
FROM pg_replication_slots
ORDER BY pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) DESC;
\endif
