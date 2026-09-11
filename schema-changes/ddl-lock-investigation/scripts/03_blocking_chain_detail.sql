/*
===============================================================================
SCRIPT NAME:
03_blocking_chain_detail.sql

PURPOSE:
Expands every blocking relationship into one row per blocker, showing what each blocker is actually doing.

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
Step 03 of workflow 'schema-changes/ddl-lock-investigation'

RELATED SCRIPTS:
04_lock_detail_by_mode.sql

HOW TO INTERPRET RESULTS:
Follow the chain to its root rather than acting on the first blocker you see -- a direct blocker may itself be blocked by something else, and only the backend that is not waiting on anything is worth acting on. The blocking_state column is the key field: a blocker in state 'idle in transaction' with a large blocking_txn_age is doing no work whatsoever while holding the lock, which is almost always a connection-pool leak or a forgotten session, and contacting the owning team is far more productive than waiting. A blocker in state 'active' with a long-running query is at least doing something, and the judgement is whether that work matters more than the stalled application -- on the trading path, it does not.
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
