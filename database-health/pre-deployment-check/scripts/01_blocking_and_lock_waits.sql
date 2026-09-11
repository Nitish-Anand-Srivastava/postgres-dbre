/*
===============================================================================
SCRIPT NAME:
01_blocking_and_lock_waits.sql

PURPOSE:
Confirms no session is currently blocked on a lock before the deployment starts.

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
Step 01 of workflow 'database-health/pre-deployment-check'

RELATED SCRIPTS:
02_strong_lock_modes_held.sql

HOW TO INTERPRET RESULTS:
An empty result is the required pass condition. Any existing blocking chain is an automatic no-go: adding a migration's lock request to an already-congested queue is how a routine deployment becomes a trading halt.
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
