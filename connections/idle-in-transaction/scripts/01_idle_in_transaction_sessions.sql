/*
===============================================================================
SCRIPT NAME:
01_idle_in_transaction_sessions.sql

PURPOSE:
Lists idle-in-transaction sessions, viewed here for their connection-slot consumption impact.

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
Step 01 of workflow 'connections/idle-in-transaction'

RELATED SCRIPTS:
../../concurrency-and-locking/idle-in-transaction/scripts/01_idle_in_transaction_sessions.sql

HOW TO INTERPRET RESULTS:
Every result here occupies a connection slot indefinitely in addition to holding locks/snapshots -- see concurrency-and-locking/idle-in-transaction for the full remediation guidance.
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
