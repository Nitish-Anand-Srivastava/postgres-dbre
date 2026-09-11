/*
===============================================================================
SCRIPT NAME:
06_long_transactions.sql

PURPOSE:
Step 6 of 10: transactions open longer than the threshold, whether or not they are currently executing anything.

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
Step 06 of workflow 'incident-response/production-triage'

RELATED SCRIPTS:
07_connection_utilization.sql, ../../concurrency-and-locking/blocked-queries/README.md

HOW TO INTERPRET RESULTS:
This is a different problem from script 05 and is frequently the quieter, more damaging one: a transaction that is idle still holds its snapshot and its locks, pinning the vacuum horizon and blocking others. Compare txn_age against the incident start -- a transaction older than the incident is a strong candidate for the trigger.
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
