/*
===============================================================================
SCRIPT NAME:
03_pre_window_topology_and_replication_check.sql

PURPOSE:
Pre-window confirmation of which instance is the writer, that every reader is healthy and low-lag, and that no replication slot is silently retaining WAL.

AURORA POSTGRESQL VERSION:
Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise)

EXECUTION LOCATION:
Any instance (writer or reader)

SAFETY:
READ ONLY

EXPECTED IMPACT:
Minimal -- reads system catalogs/statistics views only, no table locks beyond a brief catalog lookup.

REQUIRED PRIVILEGES:
Role membership in `pg_monitor` (or `pg_read_all_stats`) is sufficient. No superuser required.

PREREQUISITES:
None beyond CONNECT on the target database.

EXECUTION ORDER:
Step 03 of workflow 'maintenance/planned-maintenance-window-checklist'

RELATED SCRIPTS:
04_maintenance_window_checklist.md

HOW TO INTERPRET RESULTS:
Confirm the connection you are about to perform maintenance through is actually reaching the instance you believe it is -- is_reader_instance = true when you expect the writer means an earlier, unnoticed failover has already occurred and the window's assumptions are wrong. Every reader should show low, stable lag: performing a reboot or failover while a reader is already behind removes the very redundancy the maintenance depends on. A slot retaining a large amount of WAL, especially an inactive one, should be resolved before the window rather than discovered as a storage problem during it.
===============================================================================
*/

-- Is this instance currently a writer or a reader? On Aurora, every reader
-- instance is always in continuous recovery mode (pg_is_in_recovery() =
-- true), even though it is not a traditional PostgreSQL physical standby --
-- it is replaying redo log records shipped from the shared Aurora storage
-- layer, not a WAL stream from the writer. Always confirm this before
-- interpreting any other replication-related query on this connection.
SELECT
    pg_is_in_recovery()                                          AS is_reader_instance,
    CASE WHEN pg_is_in_recovery()
         THEN 'This connection is to an Aurora reader instance (or a standard PostgreSQL physical replica).'
         ELSE 'This connection is to the Aurora writer instance (or a standalone/primary PostgreSQL server).'
    END                                                           AS role_description;

-- Aurora-specific cluster-wide replica status and lag, callable from any
-- instance in the cluster (writer or reader). This is the correct,
-- Aurora-native way to check reader lag -- it reflects the actual Aurora
-- storage-layer replication mechanism, not standard PostgreSQL streaming
-- replication. The exact column set has evolved across Aurora PostgreSQL
-- engine releases, so this script selects all columns explicitly via
-- information_schema-free SELECT * (a documented, deliberate exception to
-- the "no bare SELECT *" rule, since the function's return type is
-- engine-version-defined rather than a fixed catalog): confirm the columns
-- returned in your environment with \x and adjust downstream automation
-- accordingly.
SELECT *
FROM aurora_replica_status()
ORDER BY 1;

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
