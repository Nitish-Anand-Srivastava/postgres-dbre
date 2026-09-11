/*
===============================================================================
SCRIPT NAME:
04_io_and_checkpoint_pressure.sql

PURPOSE:
Reports per-backend-type I/O statistics and checkpoint/background-writer activity.

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
Step 04 of workflow 'database-health/capacity-health-check'

RELATED SCRIPTS:
05_replication_slot_wal_retention.sql, ../../storage-and-capacity/wal-generation/README.md

HOW TO INTERPRET RESULTS:
A rising pct_forced_checkpoints (checkpoints triggered by hitting max_wal_size rather than the scheduled timeout) means the write rate has outgrown the current checkpoint tuning -- a capacity finding distinct from storage size. On PG17, pg_stat_io reports operation counts and a fixed op_bytes rather than direct byte columns; the derived byte totals in this query's output already account for that.
===============================================================================
*/

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

-- Background writer activity (PG17 pg_stat_bgwriter is now limited to
-- non-checkpoint buffer writes: buffers_clean/maxwritten_clean/
-- buffers_alloc). Per-backend-type I/O detail, including buffers written
-- directly by backends under memory pressure, moved to pg_stat_io in
-- PostgreSQL 16+; query that view for the fuller I/O breakdown.
SELECT
    buffers_clean,
    maxwritten_clean,
    buffers_alloc,
    stats_reset
FROM pg_stat_bgwriter;
