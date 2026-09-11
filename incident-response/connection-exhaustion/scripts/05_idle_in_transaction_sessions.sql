/*
===============================================================================
SCRIPT NAME:
05_idle_in_transaction_sessions.sql

PURPOSE:
Lists sessions holding an open transaction while idle -- slots that are also damaging vacuum and concurrency.

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
Step 05 of workflow 'incident-response/connection-exhaustion'

RELATED SCRIPTS:
06_reclaim_connection_slots.md, ../../concurrency-and-locking/blocked-queries/README.md

HOW TO INTERPRET RESULTS:
These are the highest-value reclaims because they free a slot AND release a snapshot and any locks. An idle-in-transaction session that also appears as a blocking pid in the second result set is the single best target in this workflow -- it is causing active harm while doing no work at all.
===============================================================================
*/

-- Sessions sitting idle inside an open transaction for longer than
-- :min_minutes minutes. These hold open snapshots/locks and are a very
-- common cause of autovacuum being unable to clean up dead tuples, and of
-- unexpected lock waits on otherwise unrelated statements.
\set min_minutes 5
SELECT
    pid,
    datname,
    usename,
    application_name,
    client_addr,
    state,
    backend_xid,
    backend_xmin,
    now() - xact_start                                          AS idle_txn_duration,
    now() - state_change                                        AS time_in_current_state,
    left(query, 200)                                             AS last_statement
FROM pg_stat_activity
WHERE state = 'idle in transaction'
  AND pid <> pg_backend_pid()
  AND now() - state_change > make_interval(mins => :min_minutes)
ORDER BY idle_txn_duration DESC;

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
