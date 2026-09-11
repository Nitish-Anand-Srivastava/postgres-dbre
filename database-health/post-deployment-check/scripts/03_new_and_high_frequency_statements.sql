/*
===============================================================================
SCRIPT NAME:
03_new_and_high_frequency_statements.sql

PURPOSE:
Ranks statements by call count to expose N+1 patterns and retry storms introduced by the release.

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
Step 03 of workflow 'database-health/post-deployment-check'

RELATED SCRIPTS:
04_sequential_scan_regression.sql

HOW TO INTERPRET RESULTS:
A statement whose call count exploded after the release is usually an N+1 access pattern (one query per row of a result set) or a client-side retry loop reacting to an error. Both are cheap individually and devastating in aggregate: at exchange request volumes, a per-row lookup added to the order-book read path can add tens of thousands of statements per second.
===============================================================================
*/

-- pg_stat_statements presence check. This script never creates the
-- extension itself -- it only detects whether it is already available.
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
SELECT 'pg_stat_statements is not installed in this database, so query-level '
       'statistics are unavailable for this health check. Ask an administrator '
       'to add pg_stat_statements to shared_preload_libraries in the Aurora DB '
       'cluster parameter group (reboot required) and then run '
       'CREATE EXTENSION pg_stat_statements; in a change-managed session. '
       'Until then, continue this health check with the remaining scripts -- '
       'they do not depend on this extension.'                  AS notice;
\endif
