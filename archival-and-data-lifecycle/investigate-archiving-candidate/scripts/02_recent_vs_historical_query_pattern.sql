/*
===============================================================================
SCRIPT NAME:
02_recent_vs_historical_query_pattern.sql

PURPOSE:
Reviews top queries against the table to assess whether the live application query pattern is scoped to recent data only.

AURORA POSTGRESQL VERSION:
Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise)

EXECUTION LOCATION:
Any instance (writer or reader)

SAFETY:
READ ONLY

EXPECTED IMPACT:
Minimal -- reads system catalogs/statistics views only, no table locks beyond a brief catalog lookup.

REQUIRED PRIVILEGES:
Role membership in `pg_monitor` (or `pg_read_all_stats`) is sufficient. No superuser required.

PREREQUISITES:
None beyond CONNECT on the target database.

EXECUTION ORDER:
Step 02 of workflow 'archival-and-data-lifecycle/investigate-archiving-candidate'

RELATED SCRIPTS:
../archive-large-table/README.md

HOW TO INTERPRET RESULTS:
If every frequent query's filter clause is scoped to a recent window (e.g. 'WHERE created_at > now() - interval'), historical rows are not serving live traffic and are a strong archiving candidate.
===============================================================================
*/

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
