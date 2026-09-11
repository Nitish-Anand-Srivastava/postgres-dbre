/*
===============================================================================
SCRIPT NAME:
02_statement_latency_profile.sql

PURPOSE:
Shows mean, standard deviation, and maximum execution time per statement to separate consistently slow from occasionally catastrophic.

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
Step 02 of workflow 'query-optimization/analyze-query-plan'

RELATED SCRIPTS:
03_planning_vs_execution_time.sql

HOW TO INTERPRET RESULTS:
A high mean with a low standard deviation means one stable, consistently bad plan -- analyze it directly. A modest mean with a very large max and standard deviation means the statement is parameter-sensitive: it is fast for typical values and pathological for outliers such as the single most active trading pair or the largest institutional account. That distinction determines whether you capture a plan with typical parameters or specifically with the outlier values.
===============================================================================
*/

-- pg_stat_statements presence check. This script only detects whether the
-- extension is already available; it never creates it.
SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements') AS pgss_available
\gset

\if :pgss_available
-- Top statements by mean execution time, restricted to statements called at
-- least :min_calls times so a single slow one-off migration query does not
-- crowd out genuinely slow, frequently-run application queries.
\set top_n 20
\set min_calls 20
SELECT
    queryid,
    calls,
    round(mean_exec_time::numeric, 2)                             AS mean_exec_time_ms,
    round(stddev_exec_time::numeric, 2)                           AS stddev_exec_time_ms,
    round(max_exec_time::numeric, 2)                              AS max_exec_time_ms,
    rows,
    left(query, 200)                                              AS query_snippet
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
  AND calls >= :min_calls
ORDER BY mean_exec_time DESC
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
