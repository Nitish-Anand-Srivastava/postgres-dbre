/*
===============================================================================
SCRIPT NAME:
03_wal_settings_and_position.sql

PURPOSE:
Captures WAL-related configuration and an engine-safe write-volume reference; community PostgreSQL also reports the current WAL position for rate sampling.

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
Step 03 of workflow 'storage-and-capacity/wal-generation'

RELATED SCRIPTS:
04_wal_heavy_statements.sql

HOW TO INTERPRET RESULTS:
Read the settings first: a small max_wal_size relative to your write rate is what produces the forced checkpoints seen in script 02. On Aurora, the script intentionally returns no WAL/LSN value; use CloudWatch WriteThroughput, VolumeWriteIOPs and VolumeBytesUsed as the authoritative rate and volume sources. On community PostgreSQL, run the LSN branch twice several minutes apart and subtract the positions to derive a rate.
===============================================================================
*/

-- Part 1: the WAL and checkpoint settings that determine how much WAL this
-- workload produces and how often the full-page-write cycle restarts. On
-- Aurora these come from the DB cluster parameter group, not
-- postgresql.conf; the `source` column shows whether the live value came
-- from the parameter group (reported as a configuration file), a
-- session-level SET, or the built-in default.
SELECT
    name,
    setting,
    unit,
    context,
    source,
    short_desc
FROM pg_settings
WHERE name IN (
    'wal_level', 'max_wal_size', 'min_wal_size', 'wal_compression',
    'wal_buffers', 'full_page_writes', 'synchronous_commit',
    'checkpoint_timeout', 'checkpoint_completion_target',
    'wal_keep_size', 'max_slot_wal_keep_size', 'wal_writer_delay'
)
ORDER BY name;

-- Part 2: current WAL position. Aurora PostgreSQL 17.7 rejects the upstream
-- WAL/LSN functions even for read-only inspection. Detect Aurora before
-- psql sends any statement containing those functions; use AWS-native
-- telemetry on Aurora and retain upstream LSN diagnostics only for
-- community PostgreSQL.
SELECT (
    current_setting('aurora_version', true) IS NOT NULL
    OR current_setting('rds.extensions', true) IS NOT NULL
    OR EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'aurora_version')
)                                                                AS is_aurora
\gset

\if :is_aurora
SELECT
    CASE WHEN pg_is_in_recovery() THEN 'reader' ELSE 'writer' END AS instance_role,
    clock_timestamp()                                             AS captured_at,
    current_setting('wal_level')                                  AS wal_level,
    'Aurora PostgreSQL does not expose the upstream WAL/LSN inspection '
    'functions safely. Use CloudWatch WriteThroughput, VolumeWriteIOPs and '
    'VolumeBytesUsed for write volume, Performance Insights for Log waits, '
    'and AuroraReplicaLag for reader apply delay.'                 AS guidance;
\else
SELECT pg_is_in_recovery() AS in_recovery
\gset

\if :in_recovery
SELECT
    'reader (in recovery)'::text                                  AS instance_role,
    pg_last_wal_receive_lsn()                                     AS last_wal_receive_lsn,
    pg_last_wal_replay_lsn()                                      AS last_wal_replay_lsn,
    pg_last_xact_replay_timestamp()                               AS last_replayed_xact_time,
    now() - pg_last_xact_replay_timestamp()                       AS replay_delay;
\else
SELECT
    'writer (not in recovery)'::text                              AS instance_role,
    pg_current_wal_lsn()                                          AS current_wal_lsn,
    pg_current_wal_insert_lsn()                                   AS current_wal_insert_lsn,
    pg_walfile_name(pg_current_wal_lsn())                         AS current_wal_segment,
    pg_size_pretty(
        pg_wal_lsn_diff(pg_current_wal_lsn(), '0/0'::pg_lsn)
    )                                                             AS wal_position_as_bytes,
    'Take a second sample of this script a known interval later (5 or 10 '
    'minutes is usually enough) and difference wal_position_as_bytes to get '
    'a genuine WAL bytes-per-second rate. A single sample is only a position, '
    'not a rate.'                                                 AS how_to_get_a_rate;
\endif
\endif
