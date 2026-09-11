/*
===============================================================================
SCRIPT NAME:
04_xmin_horizon_holders.sql

PURPOSE:
Finds long-running transactions, idle-in-transaction sessions, and prepared transactions that hold back the xmin horizon and block all reclamation.

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
Step 04 of workflow 'storage-and-capacity/unexpected-storage-growth'

RELATED SCRIPTS:
05_replication_slot_retention.sql

HOW TO INTERPRET RESULTS:
Any transaction open for hours pins the xmin horizon for the entire database, not only for the tables it touched, so a single forgotten session blocks reclamation everywhere. Sessions in state 'idle in transaction' are the worst case: they are doing no work at all while blocking cleanup, and they are almost always a connection-pool leak or a forgotten terminal rather than deliberate. The second result set lists prepared transactions -- any of these older than a few minutes is an orphaned two-phase commit whose coordinator died; it holds locks and the xmin horizon indefinitely and survives instance restarts, so it will never resolve on its own. Confirm ownership before ending anything, and note that clearing the holder does not reclaim space by itself -- it only lets the next vacuum do so.
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
