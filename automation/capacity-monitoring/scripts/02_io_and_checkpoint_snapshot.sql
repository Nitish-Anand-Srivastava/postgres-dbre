/*
===============================================================================
SCRIPT NAME:
02_io_and_checkpoint_snapshot.sql

PURPOSE:
Per-backend-type I/O and checkpoint-pressure snapshot, intended to be captured on every scheduled run since I/O-tier capacity is a separate dimension from raw storage bytes.

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
Step 02 of workflow 'automation/capacity-monitoring'

RELATED SCRIPTS:
03_scheduling_runbook.md

HOW TO INTERPRET RESULTS:
A rising pct_forced_checkpoints trend across successive scheduled runs, or a growing read/write byte volume attributable to a specific backend_type, is the early signal that an I/O-tier or checkpoint-tuning review is worth scheduling ahead of any user-visible latency impact -- exactly the same interpretation as storage-and-capacity/capacity-forecasting's equivalent script, just captured automatically instead of on demand.
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
