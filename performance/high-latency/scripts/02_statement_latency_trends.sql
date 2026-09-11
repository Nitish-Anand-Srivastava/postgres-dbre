/*
===============================================================================
SCRIPT NAME:
02_statement_latency_trends.sql

PURPOSE:
Statements with the highest mean execution time, called frequently enough to be a real trend rather than noise.

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
Step 02 of workflow 'performance/high-latency'

RELATED SCRIPTS:
03_lock_wait_check.sql

HOW TO INTERPRET RESULTS:
Compare against historical baselines if available (APM or a saved snapshot); a broad-based increase across many statements suggests a systemic cause (I/O, cache), while one or two standouts suggest a localized plan/index issue.
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
