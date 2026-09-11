/*
===============================================================================
SCRIPT NAME:
04_new_query_shapes.sql

PURPOSE:
Looks for new or newly frequent statements, which is how a changed code path announces itself at the database.

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
Step 04 of workflow 'incident-response/post-deployment-incident'

RELATED SCRIPTS:
05_statistics_and_scan_regression.sql

HOW TO INTERPRET RESULTS:
A statement shape with a very high call count and a small mean execution time that nobody recognizes is the classic N+1 pattern arriving in production. Compare against a saved pre-deployment capture if you have one -- this ranking is far more useful as a diff than as an absolute reading.
===============================================================================
*/

-- pg_stat_statements presence check. This script never creates the
-- extension itself -- it only detects whether it is already available,
-- so the script is safe to run blind during an incident.
SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements') AS pgss_available
\gset

\if :pgss_available
-- Top statements by call frequency. Extremely high-frequency, low-latency
-- statements are exactly what you expect for an OLTP/order-book workload;
-- the interesting signal is a sudden large increase in calls for a given
-- queryid between two snapshots (application retry storm, N+1 query
-- pattern, or a newly deployed hot loop), so save this output and diff it
-- across incidents.
\set top_n 20
SELECT
    queryid,
    calls,
    round(total_exec_time::numeric, 2)                            AS total_exec_time_ms,
    round(mean_exec_time::numeric, 4)                             AS mean_exec_time_ms,
    rows,
    left(query, 200)                                              AS query_snippet
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
ORDER BY calls DESC
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
