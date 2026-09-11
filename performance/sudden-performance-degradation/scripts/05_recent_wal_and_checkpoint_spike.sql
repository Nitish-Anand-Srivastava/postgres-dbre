/*
===============================================================================
SCRIPT NAME:
05_recent_wal_and_checkpoint_spike.sql

PURPOSE:
Checks for a recent spike in WAL generation or forced checkpoints that could correlate with the incident window.

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
Step 05 of workflow 'performance/sudden-performance-degradation'

RELATED SCRIPTS:
../../incident-response/production-triage/README.md

HOW TO INTERPRET RESULTS:
A high pct_forced_checkpoints combined with the incident's onset time suggests a burst of write activity (possibly from the same deploy/traffic spike) saturated the WAL/checkpoint subsystem.
===============================================================================
*/

-- Checkpointer statistics. PostgreSQL 17 moved these counters out of
-- pg_stat_bgwriter into their own pg_stat_checkpointer view -- do not query
-- pg_stat_bgwriter for checkpoint counters on 17, they no longer exist
-- there. Frequent num_requested (forced) checkpoints relative to num_timed
-- (scheduled) checkpoints indicates checkpoint_timeout/max_wal_size are too
-- small for the current write rate.
SELECT
    num_timed,
    num_requested,
    round(
        100.0 * num_requested / NULLIF(num_timed + num_requested, 0), 2
    )                                                            AS pct_forced_checkpoints,
    buffers_written,
    round(write_time::numeric, 2)                                 AS write_time_ms,
    round(sync_time::numeric, 2)                                  AS sync_time_ms,
    stats_reset
FROM pg_stat_checkpointer;
