/*
===============================================================================
SCRIPT NAME:
05_checkpoint_io_and_temp_pressure.sql

PURPOSE:
Checks checkpoint frequency, per-backend-type IO and temp-file volume -- the resource-pressure explanations for latency that has no blocking behind it.

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
Step 05 of workflow 'incident-response/sudden-latency-spike'

RELATED SCRIPTS:
06_statement_timing_shift.sql

HOW TO INTERPRET RESULTS:
A high pct_forced_checkpoints means write volume is outrunning max_wal_size and foreground writes are stalling. Large derived read volume attributed to client backends means queries are missing the buffer cache. A climbing temp_bytes means sorts and hashes are spilling to disk, which points at work_mem or at stale statistics producing bad row estimates.
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

-- Per-backend-type I/O statistics (added PostgreSQL 16, still current in
-- 17). Useful to see whether I/O pressure is coming from regular client
-- backends, autovacuum workers, or background writer/checkpointer activity.
--
-- IMPORTANT (verified against Aurora PostgreSQL 17.7): pg_stat_io on
-- PostgreSQL 17 does NOT have read_bytes/write_bytes/extend_bytes columns
-- -- those were only added in PostgreSQL 18. On 17, every I/O operation is
-- the same fixed size, reported separately as `op_bytes` (typically 8192,
-- one buffer page), so the actual byte volume must be derived numerically
-- as reads * op_bytes / writes * op_bytes rather than read directly.
-- Referencing read_bytes/write_bytes directly on 17 raises
-- "column does not exist".
SELECT
    backend_type,
    object,
    context,
    reads,
    op_bytes,
    pg_size_pretty((reads * op_bytes)::numeric)                   AS read_bytes_derived,
    writes,
    pg_size_pretty((writes * op_bytes)::numeric)                  AS write_bytes_derived,
    extends,
    hits,
    round(read_time::numeric, 2)                                  AS read_time_ms,
    round(write_time::numeric, 2)                                 AS write_time_ms
FROM pg_stat_io
WHERE reads > 0 OR writes > 0 OR hits > 0
ORDER BY (reads * op_bytes) DESC NULLS LAST;

-- Cumulative temp file counters per database. A rising temp_bytes rate
-- indicates queries are spilling sorts/hashes/materializations to disk,
-- most often because work_mem is undersized for the actual query shapes
-- running in production, or because statistics are stale and the planner
-- underestimates row counts.
SELECT
    datname,
    temp_files,
    pg_size_pretty(temp_bytes)                                    AS temp_bytes_total,
    stats_reset
FROM pg_stat_database
WHERE datname IS NOT NULL
ORDER BY temp_bytes DESC;
