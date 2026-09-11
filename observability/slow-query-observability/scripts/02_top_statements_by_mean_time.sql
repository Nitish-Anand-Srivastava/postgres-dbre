/*
===============================================================================
SCRIPT NAME:
02_top_statements_by_mean_time.sql

PURPOSE:
Ranks statements by mean execution time (restricted to a minimum call count) to find individually slow statements regardless of total volume.

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
Step 02 of workflow 'observability/slow-query-observability'

RELATED SCRIPTS:
03_temp_file_and_io_heavy_statements.sql

HOW TO INTERPRET RESULTS:
The minimum-calls filter keeps a single slow ad hoc/migration query from crowding out genuinely slow, recurring production statements. A high stddev_exec_time alongside a moderate mean suggests the statement's cost depends heavily on its parameters or on a data distribution that changes over time (a plan that is fast for common values and slow for rare ones), which total/mean time alone would not reveal.
===============================================================================
*/

-- pg_stat_statements presence check. This script never creates the
-- extension itself -- it only detects whether it is already available.
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
SELECT 'pg_stat_statements is not installed in this database, so query-level '
       'statistics are unavailable. Ask an administrator to add '
       'pg_stat_statements to shared_preload_libraries in the Aurora DB '
       'cluster parameter group (reboot required) and then run '
       'CREATE EXTENSION pg_stat_statements; in a change-managed session. '
       'Until then, the wait-event and CloudWatch-based observability in '
       'this category still functions without it.'                  AS notice;
\endif
