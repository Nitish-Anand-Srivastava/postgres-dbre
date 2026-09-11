/*
===============================================================================
SCRIPT NAME:
04_reader_side_long_queries.sql

PURPOSE:
Checks for long-running queries on the specific lagging reader instance that could be delaying redo application.

AURORA POSTGRESQL VERSION:
Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise)

EXECUTION LOCATION:
Reader instance specifically (connect directly to the lagging reader, not the cluster/reader load-balanced endpoint)

SAFETY:
READ ONLY

EXPECTED IMPACT:
Minimal -- reads system catalogs/statistics views only, no table locks beyond a brief catalog lookup.

REQUIRED PRIVILEGES:
Role membership in `pg_monitor` (or `pg_read_all_stats`) is sufficient. No superuser required.

PREREQUISITES:
None beyond CONNECT on the target database.

EXECUTION ORDER:
Step 04 of workflow 'replication-and-ha/replication-lag'

RELATED SCRIPTS:
../reader-lag-investigation/README.md

HOW TO INTERPRET RESULTS:
Run this connected directly to the lagging reader instance (not the writer or cluster endpoint) -- a long analytical query on the reader can itself delay how quickly it applies incoming redo.
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
