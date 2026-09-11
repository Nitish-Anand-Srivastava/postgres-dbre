/*
===============================================================================
SCRIPT NAME:
02_query_performance_vs_baseline.sql

PURPOSE:
Re-captures top statements by total time for direct comparison against the pre-deployment baseline.

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
pg_stat_statements must be present in shared_preload_libraries (Aurora DB cluster parameter group, requires a reboot to apply) and created in the current database. This script detects its absence and prints a notice instead of failing, so it is safe to run either way. The pre-deployment baseline from pre-deployment-check script 07 is required for the comparison.

EXECUTION ORDER:
Step 02 of workflow 'database-health/post-deployment-check'

RELATED SCRIPTS:
03_new_and_high_frequency_statements.sql, ../pre-deployment-check/README.md

HOW TO INTERPRET RESULTS:
Compare row by row against pre-deployment-check script 07. A pre-existing queryid whose total_exec_time share grew disproportionately, or a new queryid that immediately dominates, is the regression. Confirm stats_reset has not changed between the two captures -- if it has (for example because the deployment triggered a failover), this comparison is invalid and must be replaced with application-side latency metrics.
===============================================================================
*/

-- pg_stat_statements presence check. This script never creates the
-- extension itself -- it only detects whether it is already available.
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
SELECT 'pg_stat_statements is not installed in this database, so query-level '
       'statistics are unavailable for this health check. Ask an administrator '
       'to add pg_stat_statements to shared_preload_libraries in the Aurora DB '
       'cluster parameter group (reboot required) and then run '
       'CREATE EXTENSION pg_stat_statements; in a change-managed session. '
       'Until then, continue this health check with the remaining scripts -- '
       'they do not depend on this extension.'                  AS notice;
\endif
