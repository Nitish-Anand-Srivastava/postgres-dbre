/*
===============================================================================
SCRIPT NAME:
01_restore_point_reference_snapshot.sql

PURPOSE:
Captures a SQL-side reference point (current WAL position and database-level statistics) immediately before a scheduled test-restore, for concrete before/after comparison.

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
Step 01 of workflow 'disaster-recovery/backup-and-restore-validation'

RELATED SCRIPTS:
02_backup_and_restore_test_runbook.md

HOW TO INTERPRET RESULTS:
Save this output alongside the test-restore's own start time. After the restore completes into the scratch cluster, re-run this same query there and compare xact_commit/reference_timestamp to confirm the restored data reflects activity from at or before your intended recovery point, not unexpectedly older or newer data.
===============================================================================
*/

-- A lightweight, point-in-time reference snapshot to compare against after
-- a test-restore completes. This is a sanity/comparison aid only -- the
-- authoritative recovery-point mechanism for Aurora backups (the backup
-- window and retention period) is tracked entirely by the AWS control
-- plane, not by anything queryable here.
--
-- IMPORTANT (verified against Aurora PostgreSQL 17.7): pg_current_wal_lsn()
-- errors on Aurora clusters running with wal_level=replica (Aurora's
-- default) -- this function family depends on the same logical-WAL-cache
-- infrastructure used by logical replication, and is only reliably
-- callable once wal_level=logical is set. current_setting('wal_level') is
-- a plain GUC read that never fails, so it guards the call here: a CASE
-- expression only evaluates its matching branch (the same documented
-- mechanism used to avoid division-by-zero in a CASE), so
-- pg_current_wal_lsn() is never actually invoked unless wal_level is
-- already 'logical'.
SELECT
    current_database()                                          AS database_name,
    CASE WHEN current_setting('wal_level') = 'logical'
         THEN pg_current_wal_lsn()::text
         ELSE 'NOT AVAILABLE (wal_level=' || current_setting('wal_level') ||
              ', requires logical on Aurora)'
    END                                                          AS current_wal_lsn,
    clock_timestamp()                                           AS reference_timestamp,
    d.xact_commit,
    d.xact_rollback,
    d.stats_reset
FROM pg_stat_database d
WHERE d.datname = current_database();
