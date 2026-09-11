/*
===============================================================================
SCRIPT NAME:
01_error_and_rollback_rates.sql

PURPOSE:
Compares commit and rollback counters plus deadlock and conflict counts to detect failing code paths.

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
Step 01 of workflow 'database-health/post-deployment-check'

RELATED SCRIPTS:
02_query_performance_vs_baseline.sql

HOW TO INTERPRET RESULTS:
A rollback_pct that steps up at the deployment timestamp means transactions are failing, which is an application-code finding to route to the deploying team, not a database tuning problem. A rising deadlocks count after a release means the new version changed lock acquisition order -- on ledger and wallet tables this risks silently dropped financial writes if the application's retry logic is not correct.
===============================================================================
*/

-- Transaction outcome counters per database. A release that introduces a
-- failing code path shows up here as a rollback_pct increase long before
-- it shows up in latency metrics, because failing transactions are usually
-- fast transactions.
--
-- These counters are cumulative since stats_reset, so the absolute values
-- are not meaningful on their own: capture this immediately before and
-- after the deployment, or divide by the counting window to get a rate.
SELECT
    datname                                                      AS database_name,
    xact_commit,
    xact_rollback,
    round(100.0 * xact_rollback / NULLIF(xact_commit + xact_rollback, 0), 3) AS rollback_pct,
    deadlocks,
    conflicts,
    temp_files,
    pg_size_pretty(temp_bytes)                                    AS temp_bytes_total,
    round(100.0 * blks_hit / NULLIF(blks_hit + blks_read, 0), 2)  AS cache_hit_pct,
    stats_reset,
    now() - stats_reset                                           AS counting_window,
    round(
        (xact_commit + xact_rollback)::numeric /
        NULLIF(EXTRACT(epoch FROM (now() - stats_reset))::numeric, 0),
        2
    )                                                             AS avg_txn_per_second
FROM pg_stat_database
WHERE datname IS NOT NULL
ORDER BY xact_commit + xact_rollback DESC;
