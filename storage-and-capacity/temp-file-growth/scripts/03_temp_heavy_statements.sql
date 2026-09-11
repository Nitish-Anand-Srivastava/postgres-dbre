/*
===============================================================================
SCRIPT NAME:
03_temp_heavy_statements.sql

PURPOSE:
Attributes temporary file volume to individual statements, which is where the actionable finding almost always is.

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
`pg_stat_statements` must already be installed in this database (`shared_preload_libraries` includes it on the Aurora cluster parameter group and `CREATE EXTENSION pg_stat_statements;` has been run by an administrator in a change-managed session). This script never creates it.

EXECUTION ORDER:
Step 03 of workflow 'storage-and-capacity/temp-file-growth'

RELATED SCRIPTS:
04_sessions_spilling_now.sql

HOW TO INTERPRET RESULTS:
Expect extreme concentration: a handful of statements typically account for the vast majority of temp bytes, and fixing those removes the problem without any cluster-wide memory change. For each offender decide which of three fixes applies: a sort that an index could serve as an ordered scan (add the index, the sort node disappears entirely), a hash join whose build side was underestimated (fix statistics -- more memory will not help a wrongly sized hash table), or a genuinely large aggregation over full history (add a predicate, pre-aggregate, or move the workload off the OLTP cluster). Divide temp_blks_written by calls to distinguish one catastrophic run from a steadily expensive statement.
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
\set top_n 20
SELECT
    queryid,
    calls,
    temp_blks_written,
    temp_blks_read,
    shared_blks_read,
    round(blk_read_time::numeric, 2)                              AS blk_read_time_ms,
    round(mean_exec_time::numeric, 2)                             AS mean_exec_time_ms,
    left(query, 200)                                              AS query_snippet
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
  AND (temp_blks_written > 0 OR temp_blks_read > 0)
ORDER BY temp_blks_written DESC
LIMIT :top_n;
\else
SELECT 'pg_stat_statements is not installed in this database, so query-level '
       'statistics are unavailable for this capacity check. Ask an administrator '
       'to add pg_stat_statements to shared_preload_libraries in the Aurora DB '
       'cluster parameter group (a reboot is required) and then install the '
       'extension in a change-managed session; the exact statement is documented '
       'in the repository prerequisites guide and is deliberately never executed '
       'by an investigation script. The remaining scripts in this workflow do not '
       'depend on this extension.'
                                                                 AS notice;
\endif
