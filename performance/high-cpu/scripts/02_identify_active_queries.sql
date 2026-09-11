/*
===============================================================================
SCRIPT NAME:
02_identify_active_queries.sql

PURPOSE:
Lists currently active queries running longer than a threshold, to identify what is actively consuming CPU right now.

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
Step 02 of workflow 'performance/high-cpu'

RELATED SCRIPTS:
01_identify_database_load.sql, 03_identify_expensive_queries.sql

HOW TO INTERPRET RESULTS:
Queries appearing repeatedly here across multiple snapshots (run this script every 5-10 seconds during the incident) are the best candidates for the actual CPU driver.
===============================================================================
*/

-- Active queries currently running longer than :min_seconds seconds.
-- Adjust :min_seconds for your workload's normal latency profile; a
-- crypto-exchange OLTP path is typically sub-100ms, so even a handful of
-- seconds may already indicate a problem.
\set min_seconds 5
SELECT
    pid,
    datname,
    usename,
    application_name,
    client_addr,
    state,
    wait_event_type,
    wait_event,
    backend_xid,
    backend_xmin,
    now() - query_start                                        AS query_runtime,
    now() - xact_start                                          AS txn_runtime,
    left(query, 200)                                            AS query_snippet
FROM pg_stat_activity
WHERE state = 'active'
  AND pid <> pg_backend_pid()
  AND now() - query_start > make_interval(secs => :min_seconds)
ORDER BY query_runtime DESC;
