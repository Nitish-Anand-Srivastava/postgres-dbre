/*
===============================================================================
SCRIPT NAME:
03_database_activity_counters.sql

PURPOSE:
Cluster-wide throughput, cache efficiency, rollback ratio, deadlock, and temp file counters per database.

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
Step 03 of workflow 'database-health/comprehensive-health-check'

RELATED SCRIPTS:
04_connection_headroom_and_state.sql

HOW TO INTERPRET RESULTS:
cache_hit_pct below ~99% on an OLTP exchange database means the hot working set (open orders, account balances, recent trades) no longer fits in shared_buffers -- on Aurora every miss is a read from the distributed storage layer, so this shows up as latency before it shows up as CPU. A rollback_pct that jumps after a deployment usually means a new code path is failing and retrying rather than a database fault. Any non-zero checksum_failures is a hardware/storage integrity signal and must be escalated to AWS support immediately.
===============================================================================
*/

-- High-signal, low-cost cumulative counters for every database. Each value
-- accumulates since stats_reset, so the *rate* (value divided by the time
-- since stats_reset, or the difference between two health-check runs) is
-- what matters -- never the absolute number.
SELECT
    datname                                                      AS database_name,
    numbackends                                                  AS current_backends,
    xact_commit,
    xact_rollback,
    round(100.0 * xact_rollback / NULLIF(xact_commit + xact_rollback, 0), 2) AS rollback_pct,
    blks_hit,
    blks_read,
    round(100.0 * blks_hit / NULLIF(blks_hit + blks_read, 0), 2)  AS cache_hit_pct,
    tup_returned,
    tup_fetched,
    tup_inserted,
    tup_updated,
    tup_deleted,
    conflicts,
    deadlocks,
    temp_files,
    pg_size_pretty(temp_bytes)                                    AS temp_bytes_total,
    checksum_failures,
    stats_reset,
    now() - stats_reset                                           AS counting_window
FROM pg_stat_database
WHERE datname IS NOT NULL
ORDER BY xact_commit + xact_rollback DESC;
