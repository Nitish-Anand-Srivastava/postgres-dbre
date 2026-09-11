/*
===============================================================================
SCRIPT NAME:
05_long_running_and_idle_transactions.sql

PURPOSE:
Finds the long-running and idle-in-transaction sessions, plus prepared transactions, that sit at the root of most DDL lock incidents.

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
Step 05 of workflow 'schema-changes/ddl-lock-investigation'

RELATED SCRIPTS:
06_ddl_lock_remediation_runbook.md

HOW TO INTERPRET RESULTS:
The root cause is usually in one of these three result sets. A long-running read that is genuinely working is the most defensible blocker and the judgement is simply whether its work outranks the stalled application. An idle-in-transaction session is not defensible at all: it is holding locks while doing nothing, and it is almost always a connection-pool leak, an application that forgot to commit, or a terminal someone walked away from. A prepared transaction older than a few minutes is an orphaned two-phase commit whose coordinator died -- it holds its locks indefinitely, survives instance restarts, and will block the next attempt identically unless it is resolved. Whichever it is, note that clearing it does not by itself release the queue if a pending DDL request is still sitting at the head; cancel the DDL first.
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

-- Outstanding two-phase-commit (PREPARE TRANSACTION) entries. These hold
-- locks and prevent vacuum from advancing past their snapshot until they
-- are COMMIT PREPARED / ROLLBACK PREPARED. Aurora PostgreSQL supports
-- two-phase commit, but very few application frameworks intentionally use
-- it -- an unexpected non-empty result here is almost always a bug in a
-- distributed-transaction coordinator (e.g. XA-style ORM configuration)
-- rather than expected behavior.
SELECT
    gid,
    prepared,
    owner,
    database,
    now() - prepared                                            AS prepared_age
FROM pg_prepared_xacts
ORDER BY prepared ASC;
