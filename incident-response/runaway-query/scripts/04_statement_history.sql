/*
===============================================================================
SCRIPT NAME:
04_statement_history.sql

PURPOSE:
Checks whether this statement shape has always been expensive or has recently regressed.

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
pg_stat_statements installed in the current database; the script prints a notice and exits cleanly if it is not.

EXECUTION ORDER:
Step 04 of workflow 'incident-response/runaway-query'

RELATED SCRIPTS:
../../performance/high-cpu/README.md

HOW TO INTERPRET RESULTS:
Match on the query snippet. High temp_blks_written with a modest call count is a work_mem or statistics problem; a statement that is normally cheap and is expensive only right now is a plan regression worth a full deep-dive after the incident. A statement that has always been this expensive belongs on a reader, not on the writer.
===============================================================================
*/

-- pg_stat_statements presence check. This script never creates the
-- extension itself -- it only detects whether it is already available,
-- so the script is safe to run blind during an incident.
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
       'history is unavailable for this triage step. Ask an administrator to add '
       'pg_stat_statements to shared_preload_libraries in the Aurora DB cluster '
       'parameter group (a reboot is required for that change) and then install '
       'the extension in a change-managed session -- an investigation script must '
       'never do that for you mid-incident. Continue the checklist with the '
       'remaining scripts; none of them depend on this extension.' AS notice;
\endif
