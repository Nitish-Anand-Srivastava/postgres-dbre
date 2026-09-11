/*
===============================================================================
SCRIPT NAME:
03_temp_file_and_io_heavy_statements.sql

PURPOSE:
Ranks statements by temp file and shared-buffer I/O volume, surfacing memory/I/O pressure independent of raw latency.

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
pg_stat_statements must be present in shared_preload_libraries (Aurora DB cluster parameter group, requires a reboot to apply) and created in the current database. This script detects its absence and prints a notice instead of failing, so it is safe to run either way.

EXECUTION ORDER:
Step 03 of workflow 'observability/slow-query-observability'

RELATED SCRIPTS:
04_configuring_log_min_duration_and_auto_explain.md

HOW TO INTERPRET RESULTS:
A statement here with only moderate mean_exec_time is still worth investigating: it is consuming memory (spilling to temp files) or I/O (high shared_blks_read) disproportionate to its apparent cost, and that capacity is shared with every other concurrent query on the instance. This view frequently surfaces the root cause behind a work_mem or statistics-staleness finding elsewhere in this repository.
===============================================================================
*/

-- pg_stat_statements presence check. This script never creates the
-- extension itself -- it only detects whether it is already available.
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
SELECT 'pg_stat_statements is not installed in this database, so query-level '
       'statistics are unavailable. Ask an administrator to add '
       'pg_stat_statements to shared_preload_libraries in the Aurora DB '
       'cluster parameter group (reboot required) and then run '
       'CREATE EXTENSION pg_stat_statements; in a change-managed session. '
       'Until then, the wait-event and CloudWatch-based observability in '
       'this category still functions without it.'                  AS notice;
\endif
