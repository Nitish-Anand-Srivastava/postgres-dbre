/*
===============================================================================
SCRIPT NAME:
05_open_transaction_horizon.sql

PURPOSE:
Identifies the oldest open transactions and any outstanding prepared (two-phase commit) transactions.

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
Step 05 of workflow 'database-health/comprehensive-health-check'

RELATED SCRIPTS:
06_blocking_and_lock_waits.sql, ../../concurrency-and-locking/long-running-transactions/README.md

HOW TO INTERPRET RESULTS:
This is the single most important step to read before scripts 06-09: one old transaction holds back the global vacuum horizon and simultaneously produces rising dead tuples, unreclaimable bloat, growing XID age, and lock waits. An 'idle in transaction' entry is an application bug (a connection checked out of the pool with an open transaction and never committed). Any row at all in the prepared-transactions result on an exchange stack is almost always an abandoned distributed-transaction coordinator entry and must be resolved by its owner -- it blocks cleanup indefinitely and survives reconnects.
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
