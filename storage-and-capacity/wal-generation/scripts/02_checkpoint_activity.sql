/*
===============================================================================
SCRIPT NAME:
02_checkpoint_activity.sql

PURPOSE:
Reports checkpoint frequency and the forced-versus-timed split, the most common tunable cause of WAL amplification.

AURORA POSTGRESQL VERSION:
Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise)

EXECUTION LOCATION:
Writer instance preferred; safe to run on a reader but results reflect only that reader's local activity

SAFETY:
READ ONLY

EXPECTED IMPACT:
Minimal -- reads system catalogs/statistics views only, no table locks beyond a brief catalog lookup.

REQUIRED PRIVILEGES:
Role membership in `pg_monitor` (or `pg_read_all_stats`) is sufficient. No superuser required.

PREREQUISITES:
None beyond CONNECT on the target database.

EXECUTION ORDER:
Step 02 of workflow 'storage-and-capacity/wal-generation'

RELATED SCRIPTS:
03_wal_settings_and_position.sql

HOW TO INTERPRET RESULTS:
pct_forced_checkpoints above roughly 10% means max_wal_size is too small for the current write rate. This matters more than it first appears: every checkpoint restarts the full-page-write cycle, so the first write to each page after a checkpoint logs the entire page. Frequent checkpoints therefore multiply total WAL volume rather than just rescheduling it, and raising max_wal_size in the Aurora cluster parameter group is usually the single highest-leverage change available. Note that PostgreSQL 17 moved these counters out of pg_stat_bgwriter into pg_stat_checkpointer -- querying the old location returns nothing useful.
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
