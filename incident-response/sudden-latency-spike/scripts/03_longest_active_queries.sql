/*
===============================================================================
SCRIPT NAME:
03_longest_active_queries.sql

PURPOSE:
Lists the currently active queries running longest, to see whether one statement shape dominates the new latency.

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
Step 03 of workflow 'incident-response/sudden-latency-spike'

RELATED SCRIPTS:
04_blocking_snapshot.sql, ../runaway-query/README.md

HOW TO INTERPRET RESULTS:
Repetition is the signal: the same normalized statement appearing many times with a runtime far above its usual profile is a regressed statement. A single unique long query alongside otherwise-normal traffic is a runaway query instead, and belongs in that workflow.
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
