/*
===============================================================================
SCRIPT NAME:
01_target_restore_time_reference.sql

PURPOSE:
Given an operator-supplied suspected incident-start timestamp, computes a suggested restore-to target slightly earlier, alongside a safe engine-specific recovery reference.

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
suggested_restore_target_time is what you pass to --restore-to-time in the runbook's AWS CLI command. On Aurora, use current_server_time only as a clock anchor and obtain the authoritative recovery window from the AWS RDS EarliestRestorableTime and LatestRestorableTime fields; Aurora does not safely expose the upstream WAL/LSN reference functions. On community PostgreSQL, the LSN column is an additional reference, not a claim about which LSN existed at the target timestamp.
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
--
-- IMPORTANT (verified against Aurora PostgreSQL 17.7): Aurora rejects the
-- PostgreSQL WAL/LSN functions even in a CASE branch that would not return
-- their value. Detect Aurora in psql first so no statement containing an LSN
-- function is sent to the Aurora server at all.
\set incident_start_time '2025-01-01 00:00:00+00'
SELECT (
    current_setting('aurora_version', true) IS NOT NULL
    OR current_setting('rds.extensions', true) IS NOT NULL
    OR EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'aurora_version')
)                                                                AS is_aurora
\gset

\if :is_aurora
SELECT
    :'incident_start_time'::timestamptz                          AS operator_supplied_incident_start,
    (:'incident_start_time'::timestamptz - interval '5 minutes')  AS suggested_restore_target_time,
    now()                                                         AS current_server_time,
    current_user                                                  AS connected_role,
    current_setting('wal_level')                                  AS wal_level,
    extract(epoch FROM :'incident_start_time'::timestamptz)        AS incident_start_epoch_seconds,
    'Aurora PostgreSQL does not expose a safe SQL WAL/LSN reference here. '
    'Use the AWS RDS LatestRestorableTime and EarliestRestorableTime values '
    'as the authoritative PITR boundaries.'                       AS guidance;
\else
SELECT pg_is_in_recovery()                                       AS is_reader_instance
\gset

\if :is_reader_instance
SELECT
    :'incident_start_time'::timestamptz                          AS operator_supplied_incident_start,
    (:'incident_start_time'::timestamptz - interval '5 minutes')  AS suggested_restore_target_time,
    now()                                                         AS current_server_time,
    pg_last_wal_replay_lsn()                                      AS current_wal_lsn_for_reference,
    extract(epoch FROM :'incident_start_time'::timestamptz)        AS incident_start_epoch_seconds;
\else
SELECT
    :'incident_start_time'::timestamptz                          AS operator_supplied_incident_start,
    (:'incident_start_time'::timestamptz - interval '5 minutes')  AS suggested_restore_target_time,
    now()                                                         AS current_server_time,
    pg_current_wal_lsn()                                          AS current_wal_lsn_for_reference,
    extract(epoch FROM :'incident_start_time'::timestamptz)        AS incident_start_epoch_seconds;
\endif
\endif
