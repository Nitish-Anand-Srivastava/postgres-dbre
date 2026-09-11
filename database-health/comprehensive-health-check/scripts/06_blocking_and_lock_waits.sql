/*
===============================================================================
SCRIPT NAME:
06_blocking_and_lock_waits.sql

PURPOSE:
Checks for sessions currently blocked on locks and identifies which sessions are blocking them.

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
Step 06 of workflow 'database-health/comprehensive-health-check'

RELATED SCRIPTS:
07_dead_tuples_and_vacuum_status.sql, ../../concurrency-and-locking/blocked-queries/README.md

HOW TO INTERPRET RESULTS:
An empty result is the expected healthy state and takes one second to confirm. Any blocked session on wallets, ledger_entries, or withdrawals is immediately actionable: those paths are latency-sensitive and user-visible, and a blocking chain there tends to cascade into pool exhaustion as retries queue up behind the original blocker.
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
