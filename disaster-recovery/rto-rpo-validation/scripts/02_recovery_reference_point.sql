/*
===============================================================================
SCRIPT NAME:
02_recovery_reference_point.sql

PURPOSE:
Records a durable, engine-safe reference point (server time and commit counters, plus LSN only where supported) for comparing against a restored cluster after a drill.

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
Step 02 of workflow 'disaster-recovery/rto-rpo-validation'

RELATED SCRIPTS:
03_rto_rpo_measurement_runbook.md

HOW TO INTERPRET RESULTS:
On Aurora, compare reference_timestamp and the database commit counters against the restored cluster, then use the AWS control-plane EarliestRestorableTime and LatestRestorableTime values as the authoritative PITR boundary; the upstream WAL/LSN functions are unavailable. On community PostgreSQL, current_wal_lsn or replay_behind_by provides an additional engine reference. Capture this on a schedule (see automation/health-checks) as well as immediately before each drill, so a real incident has a recent anchor even when nobody had time to capture one.
===============================================================================
*/

-- A reference point to capture on a schedule and immediately before any
-- drill, so that "how much did we lose" can be answered by comparison
-- rather than estimation after a restore.
--
-- Aurora PostgreSQL 17.7 rejects both current and replay LSN functions.
-- Detect Aurora before psql sends any statement containing those function
-- names. The Aurora branch records a timestamp and database counters, then
-- directs the operator to the AWS control-plane recovery boundary.
SELECT (
    current_setting('aurora_version', true) IS NOT NULL
    OR current_setting('rds.extensions', true) IS NOT NULL
    OR EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'aurora_version')
)                                                                AS is_aurora
\gset

\if :is_aurora
SELECT
    current_database()                                           AS database_name,
    current_user                                                  AS connected_role,
    pg_is_in_recovery()                                           AS is_reader_instance,
    current_setting('wal_level')                                  AS wal_level,
    clock_timestamp()                                             AS reference_timestamp,
    'Use RDS EarliestRestorableTime and LatestRestorableTime for the '
    'Aurora PITR recovery boundary, and CloudWatch AuroraReplicaLag for '
    'reader staleness. Aurora SQL WAL/LSN functions are unavailable.' AS guidance;
\else
SELECT pg_is_in_recovery()                                       AS is_reader_instance
\gset

\if :is_reader_instance
SELECT
    current_database()                                           AS database_name,
    true                                                         AS is_reader_instance,
    pg_last_wal_replay_lsn()                                      AS last_replayed_lsn,
    pg_last_xact_replay_timestamp()                               AS last_replayed_commit_time,
    now() - pg_last_xact_replay_timestamp()                       AS replay_behind_by,
    clock_timestamp()                                             AS reference_timestamp;
\else
SELECT
    current_database()                                           AS database_name,
    false                                                        AS is_reader_instance,
    pg_current_wal_lsn()                                          AS current_wal_lsn,
    clock_timestamp()                                            AS reference_timestamp;
\endif
\endif

-- Commit/rollback counters for the current database, valid on either
-- instance role. Captured alongside the reference point above, these give a
-- concrete before/after comparison against a restored cluster.
SELECT
    datname                                                      AS database_name,
    xact_commit,
    xact_rollback,
    stats_reset,
    now()                                                        AS captured_at
FROM pg_stat_database
WHERE datname = current_database();
