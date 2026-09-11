/*
===============================================================================
SCRIPT NAME:
02_blocked_sessions_overview.sql

PURPOSE:
Lists every currently blocked session with its direct blockers, establishing how much of the application is actually stalled.

AURORA POSTGRESQL VERSION:
Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise)

EXECUTION LOCATION:
Writer instance preferred; safe to run on a reader but results reflect only that reader's local activity

SAFETY:
READ ONLY

EXPECTED IMPACT:
Minimal -- reads system catalogs/statistics views only, no table locks beyond a brief catalog lookup.

REQUIRED PRIVILEGES:
Role membership in `pg_monitor` (or `pg_read_all_stats`) is sufficient. No superuser required.

PREREQUISITES:
None beyond CONNECT on the target database.

EXECUTION ORDER:
Step 02 of workflow 'schema-changes/ddl-lock-investigation'

RELATED SCRIPTS:
03_blocking_chain_detail.sql

HOW TO INTERPRET RESULTS:
Use this to size the incident. A handful of blocked sessions is a contention problem; dozens or hundreds all waiting on the same relation is a full lock queue and an outage in progress. Read blocked_duration to see how long this has been going on, and blocking_pids to see whether everything converges on a single culprit -- which it usually does. If the blocked queries are ordinary application statements against one table and the blocking_pids array repeatedly names the same process, you already know the shape of the problem and script 03 will name the root.
===============================================================================
*/

-- Every session currently blocked waiting on at least one lock, and the
-- pid(s) directly blocking it via the built-in pg_blocking_pids() helper
-- (this correctly follows lock-wait-queue order, unlike a naive self-join
-- on pg_locks).
SELECT
    blocked.pid                                                 AS blocked_pid,
    blocked.usename                                              AS blocked_user,
    blocked.datname                                              AS blocked_database,
    blocked.state                                                AS blocked_state,
    now() - blocked.query_start                                  AS blocked_duration,
    pg_blocking_pids(blocked.pid)                                AS blocking_pids,
    left(blocked.query, 200)                                     AS blocked_query
FROM pg_stat_activity blocked
WHERE cardinality(pg_blocking_pids(blocked.pid)) > 0
ORDER BY blocked_duration DESC;
