/*
===============================================================================
SCRIPT NAME:
01_transaction_commit_rate.sql

PURPOSE:
Reports cumulative commit/rollback counters per database to compute a commit rate across two snapshots.

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
Step 01 of workflow 'performance/throughput-degradation'

RELATED SCRIPTS:
02_lock_serialization_check.sql

HOW TO INTERPRET RESULTS:
Compute (xact_commit_now - xact_commit_before) / elapsed_seconds and compare against the known baseline rate. A rising rollback_pct alongside falling throughput suggests contention causing serialization failures/retries, not just raw slowness.
===============================================================================
*/

-- Run this script, wait N seconds (or minutes for a batch job), then run it
-- again: the delta in xact_commit divided by the elapsed time is the
-- current transaction commit rate (transactions/sec) for that database.
SELECT
    datname,
    xact_commit,
    xact_rollback,
    round(100.0 * xact_rollback / NULLIF(xact_commit + xact_rollback, 0), 3) AS rollback_pct,
    numbackends,
    stats_reset
FROM pg_stat_database
WHERE datname IS NOT NULL
ORDER BY xact_commit DESC;
