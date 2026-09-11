/*
===============================================================================
SCRIPT NAME:
04_io_and_checkpoint_metrics.sql

PURPOSE:
Per-backend-type I/O statistics plus checkpointer and background-writer activity.

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
Step 04 of workflow 'observability/postgres-metrics'

RELATED SCRIPTS:
05_wal_generation_metrics.sql

HOW TO INTERPRET RESULTS:
pct_forced_checkpoints climbing over successive collections is one of the earliest SQL-visible signs that write volume has outgrown the current checkpoint tuning, often visible here before it shows up in CloudWatch's storage-layer metrics. Remember that on PostgreSQL 17 byte volumes in pg_stat_io are derived (reads/writes times a fixed op_bytes), not read directly from a byte column.
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
