/*
===============================================================================
SCRIPT NAME:
01_target_restore_time_reference.sql

PURPOSE:
Given an operator-supplied suspected incident-start timestamp, computes a suggested restore-to target slightly earlier, alongside the current server time and WAL position for reference.

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
Step 01 of workflow 'disaster-recovery/point-in-time-recovery-drill'

RELATED SCRIPTS:
02_point_in_time_recovery_runbook.md

HOW TO INTERPRET RESULTS:
suggested_restore_target_time is what you pass to --restore-to-time in the runbook's AWS CLI command; current_wal_lsn_for_reference and current_server_time are only a sanity-check anchor for how far 'now' is from the target, not a claim about what LSN existed at the target time itself, since Aurora's PITR mechanism resolves the target time internally rather than from this query.
===============================================================================
*/

-- Ships with an illustrative default incident_start_time -- override it with
-- the actual suspected incident-start timestamp (from application logs or
-- deployment records) via `-v incident_start_time='...'` or `\set` before
-- running. The suggested target is intentionally a few minutes earlier than
-- the supplied time: it is safer to restore a little too early (the bad
-- data is still present in the restored copy, easy to identify and ignore)
-- than a little too late (the restore already contains the problem you are
-- trying to recover from).
\set incident_start_time '2025-01-01 00:00:00+00'
SELECT
    :'incident_start_time'::timestamptz                          AS operator_supplied_incident_start,
    (:'incident_start_time'::timestamptz - interval '5 minutes')  AS suggested_restore_target_time,
    now()                                                         AS current_server_time,
    pg_current_wal_lsn()                                          AS current_wal_lsn_for_reference,
    extract(epoch FROM :'incident_start_time'::timestamptz)        AS incident_start_epoch_seconds;
