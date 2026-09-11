/*
===============================================================================
SCRIPT NAME:
01_latency_distribution_by_statement.sql

PURPOSE:
Finds statements whose execution time distribution is widest, the statistical signature of a plan change.

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
Step 01 of workflow 'query-optimization/query-plan-regression'

RELATED SCRIPTS:
02_planning_time_check.sql

HOW TO INTERPRET RESULTS:
A coefficient_of_variation above 1 combined with a max_to_mean_ratio in the tens is the clearest available evidence of more than one plan for the same statement. On an exchange, check the order-placement and balance-lookup statements here first regardless of their ranking. Remember these are aggregates over the whole window since stats_reset: a regression that started an hour ago inside a week-long window will look mild here and severe in the application's own latency metrics, and the application metrics are the more accurate view of now.
===============================================================================
*/

-- pg_stat_statements presence check. This script only detects whether the
-- extension is already available; it never creates it.
SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements') AS pgss_available
\gset

\if :pgss_available
-- Latency distribution per statement. A regression that began partway
-- through the statistics window barely moves the mean, but it moves the
-- maximum and the standard deviation immediately -- which is why those,
-- not the mean, are the right regression detectors.
--
-- coefficient_of_variation (stddev / mean) normalizes the spread so
-- statements of very different absolute speeds can be compared directly.
-- A value well above 1 means executions are not homogeneous: either two
-- plans are in use, or one plan behaves very differently across parameter
-- values.
\set top_n 25
\set min_calls 50
SELECT
    queryid,
    calls,
    round(min_exec_time::numeric, 3)                              AS min_exec_time_ms,
    round(mean_exec_time::numeric, 3)                             AS mean_exec_time_ms,
    round(max_exec_time::numeric, 3)                              AS max_exec_time_ms,
    round(stddev_exec_time::numeric, 3)                           AS stddev_exec_time_ms,
    round(
        stddev_exec_time::numeric / NULLIF(mean_exec_time::numeric, 0), 2
    )                                                             AS coefficient_of_variation,
    round(
        max_exec_time::numeric / NULLIF(mean_exec_time::numeric, 0), 1
    )                                                             AS max_to_mean_ratio,
    rows,
    shared_blks_read,
    temp_blks_written,
    left(query, 200)                                              AS query_snippet
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
  AND calls >= :min_calls
ORDER BY stddev_exec_time DESC
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
