/*
===============================================================================
SCRIPT NAME:
01_statements_writing_temp_files.sql

PURPOSE:
Ranks statements by temporary block volume, the statement-level signature of a spilling hash join.

AURORA POSTGRESQL VERSION:
Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise)

EXECUTION LOCATION:
Any instance (writer or reader)

SAFETY:
READ ONLY

EXPECTED IMPACT:
Minimal -- reads system catalogs/statistics views only, no table locks beyond a brief catalog lookup.

REQUIRED PRIVILEGES:
Role membership in `pg_monitor`, plus SELECT on `pg_stat_statements` (granted automatically to `pg_read_all_stats` once the extension is created; otherwise `GRANT SELECT ON pg_stat_statements TO <role>;`).

PREREQUISITES:
pg_stat_statements must be listed in shared_preload_libraries (an Aurora DB cluster parameter-group change that requires a reboot) and created in the current database. This script detects its absence and prints an instructional notice instead of failing, so it is safe to run either way.

EXECUTION ORDER:
Step 01 of workflow 'query-optimization/hash-join-analysis'

RELATED SCRIPTS:
02_cluster_temp_file_trend.sql

HOW TO INTERPRET RESULTS:
Every statement listed here is spilling something to disk. This view cannot tell you whether the spill is a hash join, a sort, or a materialize -- that requires the plan -- but it gives you the ranked candidate list and the queryid to investigate. Divide temp_blks_written by calls: a statement that spills a little on every one of a million calls is a very different problem from a monthly report that spills enormously once.
===============================================================================
*/

-- pg_stat_statements presence check. This script only detects whether the
-- extension is already available; it never creates it.
SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements') AS pgss_available
\gset

\if :pgss_available
-- Statements generating the most temp file I/O and shared buffer reads --
-- a direct indicator of work_mem being too small for a sort/hash/group-by,
-- or of a query reading far more data (a poor index choice, a missing
-- predicate) than a well-planned query should need.
--
-- IMPORTANT (verified against Aurora PostgreSQL 17.7): pg_stat_statements
-- 1.11, bundled with PostgreSQL/Aurora PostgreSQL 17, split the older
-- generic blk_read_time/blk_write_time columns into separate
-- shared/local/temp variants -- shared_blk_read_time, shared_blk_write_time,
-- local_blk_read_time, local_blk_write_time, temp_blk_read_time,
-- temp_blk_write_time. The bare blk_read_time/blk_write_time column names
-- no longer exist at all on 17, so referencing them raises "column does
-- not exist" rather than returning zero. This script reads
-- shared_blk_read_time (the direct 1.11 successor covering ordinary shared
-- buffer reads, which is what this script is measuring) instead.
\set top_n 20
SELECT
    queryid,
    calls,
    temp_blks_written,
    temp_blks_read,
    shared_blks_read,
    round(shared_blk_read_time::numeric, 2)                       AS shared_blk_read_time_ms,
    round(mean_exec_time::numeric, 2)                             AS mean_exec_time_ms,
    left(query, 200)                                              AS query_snippet
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
  AND (temp_blks_written > 0 OR temp_blks_read > 0)
ORDER BY temp_blks_written DESC
LIMIT :top_n;
\else
SELECT 'pg_stat_statements is not installed in this database, so statement-level '
       'statistics are unavailable. Ask an administrator to add '
       'pg_stat_statements to shared_preload_libraries in the Aurora DB cluster '
       'parameter group (a reboot is required for that change to take effect) '
       'and then run CREATE EXTENSION pg_stat_statements; in a change-managed '
       'session. Without it, query-level investigation must fall back to '
       'application-side latency metrics plus the catalog and table-level '
       'statistics used by the other scripts in this workflow.'  AS notice;
\endif
