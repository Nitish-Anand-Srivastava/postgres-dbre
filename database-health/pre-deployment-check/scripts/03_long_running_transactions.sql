/*
===============================================================================
SCRIPT NAME:
03_long_running_transactions.sql

PURPOSE:
Identifies open transactions that a DDL lock request would queue behind.

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
Step 03 of workflow 'database-health/pre-deployment-check'

RELATED SCRIPTS:
04_connection_headroom.sql, ../../concurrency-and-locking/long-running-transactions/README.md

HOW TO INTERPRET RESULTS:
This is the single highest-value pre-deployment check. A migration needing an AccessExclusiveLock cannot acquire it until every existing transaction touching that table commits -- and while it waits, all newly arriving queries on that table queue behind it. One forgotten reconciliation transaction can therefore convert a millisecond ALTER into a multi-minute outage on the orders table.
===============================================================================
*/

-- Transactions (not just active queries) open longer than :min_minutes
-- minutes, ordered by age. A transaction can be "idle in transaction" or
-- actively running a query and still be the oldest open transaction on the
-- instance -- which is what actually matters for vacuum horizon and lock
-- retention, not just the current query's runtime.
\set min_minutes 5
SELECT
    pid,
    datname,
    usename,
    state,
    backend_xid,
    backend_xmin,
    now() - xact_start                                          AS txn_age,
    left(query, 160)                                             AS current_or_last_query
FROM pg_stat_activity
WHERE xact_start IS NOT NULL
  AND now() - xact_start > make_interval(mins => :min_minutes)
ORDER BY txn_age DESC;

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
