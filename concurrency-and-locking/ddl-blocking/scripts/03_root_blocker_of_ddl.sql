/*
===============================================================================
SCRIPT NAME:
03_root_blocker_of_ddl.sql

PURPOSE:
Identifies the original long-running transaction that the DDL statement itself is waiting on.

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
Step 03 of workflow 'concurrency-and-locking/ddl-blocking'

RELATED SCRIPTS:
../../schema-changes/ddl-lock-investigation/README.md

HOW TO INTERPRET RESULTS:
This is the true root cause -- an old transaction that existed before the DDL was even issued. Resolving it (or cancelling the DDL instead) are your two options.
===============================================================================
*/

-- For every blocked session, expand pg_blocking_pids() into one row per
-- blocker and show what the blocker itself is doing, so the operator can
-- decide whether to wait, escalate, or (rarely, and only if authorized)
-- terminate the blocking backend.
SELECT
    blocked.pid                                                 AS blocked_pid,
    blocked.usename                                              AS blocked_user,
    left(blocked.query, 120)                                     AS blocked_query,
    blocker.pid                                                  AS blocking_pid,
    blocker.usename                                              AS blocking_user,
    blocker.state                                                AS blocking_state,
    now() - blocker.xact_start                                   AS blocking_txn_age,
    left(blocker.query, 120)                                     AS blocking_last_query
FROM pg_stat_activity blocked
CROSS JOIN LATERAL unnest(pg_blocking_pids(blocked.pid)) AS bp(blocking_pid)
JOIN pg_stat_activity blocker ON blocker.pid = bp.blocking_pid
ORDER BY blocking_txn_age DESC;
