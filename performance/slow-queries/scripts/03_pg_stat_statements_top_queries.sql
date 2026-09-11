/*
===============================================================================
SCRIPT NAME:
03_pg_stat_statements_top_queries.sql

PURPOSE:
Looks up historical call/timing statistics for the query pattern from pg_stat_statements.

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
Step 03 of workflow 'performance/slow-queries'

RELATED SCRIPTS:
02_long_running_queries.sql, 08_execution_plan_guidance.md

HOW TO INTERPRET RESULTS:
Compare mean_exec_time against stddev_exec_time and max_exec_time: a wide spread suggests contention or parameter-sensitivity rather than a uniformly bad plan.
===============================================================================
*/

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
