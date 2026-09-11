/*
===============================================================================
SCRIPT NAME:
07_connection_and_lock_behavior.sql

PURPOSE:
Compares per-application connection counts and checks for new lock contention after the release.

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
Step 07 of workflow 'database-health/post-deployment-check'

RELATED SCRIPTS:
../../concurrency-and-locking/blocked-queries/README.md

HOW TO INTERPRET RESULTS:
A changed connection count for the deployed service usually means its pool configuration changed with the release -- verify that was intentional. New blocking chains that did not exist before the deployment indicate the new version changed transaction boundaries or lock ordering; on wallets and ledger_entries that is a financial-operation risk and warrants immediate escalation rather than monitoring.
===============================================================================
*/

-- Connection counts broken down by application_name and usename. Useful to
-- identify which service, connection pool, or batch job is responsible for
-- a spike or leak in connection count.
SELECT
    coalesce(NULLIF(application_name, ''), '(unset)')           AS application_name,
    usename,
    datname,
    count(*)                                                    AS session_count,
    count(*) FILTER (WHERE state = 'active')                    AS active_count,
    count(*) FILTER (WHERE state = 'idle')                      AS idle_count,
    count(*) FILTER (WHERE state = 'idle in transaction')       AS idle_in_txn_count
FROM pg_stat_activity
WHERE pid <> pg_backend_pid()
GROUP BY application_name, usename, datname
ORDER BY session_count DESC;

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
