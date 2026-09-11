/*
===============================================================================
SCRIPT NAME:
03_top_queries_by_total_time.sql

PURPOSE:
Identifies the queries contributing the most cumulative execution time in the current window.

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
pg_stat_statements extension must be created in the current database.

EXECUTION ORDER:
Step 03 of workflow 'performance/high-database-load'

RELATED SCRIPTS:
04_autovacuum_contribution.sql

HOW TO INTERPRET RESULTS:
Look for several moderately expensive queries collectively dominating, not necessarily one single smoking gun -- this is the key difference from a classic single-query high-cpu incident.
===============================================================================
*/

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
