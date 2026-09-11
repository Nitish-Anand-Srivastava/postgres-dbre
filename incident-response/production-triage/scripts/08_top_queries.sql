/*
===============================================================================
SCRIPT NAME:
08_top_queries.sql

PURPOSE:
Step 8 of 10: top statements by cumulative execution time from pg_stat_statements.

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
pg_stat_statements installed in the current database; the script prints a notice and exits cleanly if it is not, so the checklist is never interrupted.

EXECUTION ORDER:
Step 08 of workflow 'incident-response/production-triage'

RELATED SCRIPTS:
09_vacuum_autovacuum.sql, ../../performance/high-cpu/README.md

HOW TO INTERPRET RESULTS:
Rank by total_exec_time, never by mean: a 3ms statement called two million times costs far more than a five-second report run twice. A low cache_hit_pct on a top consumer means it is driving IO as well as CPU. If the extension is absent the script prints a notice and the checklist continues -- do not stop here.
===============================================================================
*/

-- pg_stat_statements presence check. This script never creates the
-- extension itself -- it only detects whether it is already available,
-- so the script is safe to run blind during an incident.
SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements') AS pgss_available
\gset

\if :pgss_available
-- Top statements by total execution time -- the single best "where is the
-- database spending its time" view. Requires the pg_stat_statements
-- extension to be created in the current database and
-- shared_preload_libraries to include pg_stat_statements at the cluster
-- level (an Aurora/RDS parameter-group change requiring a reboot to apply).
\set top_n 20
SELECT
    userid::regrole                                             AS run_as_role,
    queryid,
    calls,
    round(total_exec_time::numeric, 2)                            AS total_exec_time_ms,
    round(mean_exec_time::numeric, 2)                             AS mean_exec_time_ms,
    rows,
    round(100.0 * shared_blks_hit / NULLIF(shared_blks_hit + shared_blks_read, 0), 2) AS cache_hit_pct,
    temp_blks_written,
    left(query, 200)                                              AS query_snippet
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
ORDER BY total_exec_time DESC
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
