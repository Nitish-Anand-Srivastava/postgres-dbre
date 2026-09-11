/*
===============================================================================
SCRIPT NAME:
01_rollback_rate_by_database.sql

PURPOSE:
Checks the transaction rollback rate per database as a proxy for contention-driven aborts (including serialization failures).

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
Step 01 of workflow 'concurrency-and-locking/transaction-contention'

RELATED SCRIPTS:
02_current_isolation_levels.sql

HOW TO INTERPRET RESULTS:
A high or rising rollback_pct alongside otherwise-normal query performance suggests contention-driven aborts/retries rather than raw slow queries.
===============================================================================
*/

-- Cumulative deadlock counters per database since the last stats reset.
-- This does not show individual deadlock events (those are only visible in
-- the PostgreSQL log with log_lock_waits / deadlock_timeout logging, which
-- on Aurora is surfaced through CloudWatch Logs for the instance), but a
-- rising counter confirms deadlocks are actually occurring and lets you
-- correlate the timing with an incident window.
SELECT
    datname,
    deadlocks,
    xact_commit,
    xact_rollback,
    round(100.0 * deadlocks / NULLIF(xact_commit + xact_rollback, 0), 4) AS deadlocks_per_100_txn,
    stats_reset
FROM pg_stat_database
WHERE datname IS NOT NULL
ORDER BY deadlocks DESC;
