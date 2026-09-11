/*
===============================================================================
SCRIPT NAME:
02_database_throughput_and_cache_metrics.sql

PURPOSE:
Per-database cumulative throughput, cache hit ratio, rollback ratio, deadlocks, and temp file counters.

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
Step 02 of workflow 'observability/postgres-metrics'

RELATED SCRIPTS:
03_table_and_index_activity_metrics.sql

HOW TO INTERPRET RESULTS:
cache_hit_pct is the single most useful number in this view for an OLTP exchange workload -- a sustained drop below roughly 99% means the working set no longer fits in shared_buffers, and on Aurora every miss becomes a network round trip to the distributed storage layer rather than a local page read. Alert on checksum_failures at any non-zero value; it is a storage integrity signal, not a performance one, and must go straight to AWS support.
===============================================================================
*/

-- The cheapest broad health signal available: one row per database,
-- refreshed continuously by PostgreSQL itself. Every value is cumulative
-- since stats_reset -- a monitoring pipeline should store the raw counters
-- and compute rates/deltas downstream, not just the latest snapshot.
SELECT
    datname                                                      AS database_name,
    numbackends                                                  AS current_backends,
    xact_commit,
    xact_rollback,
    round(100.0 * xact_rollback / NULLIF(xact_commit + xact_rollback, 0), 2) AS rollback_pct,
    blks_hit,
    blks_read,
    round(100.0 * blks_hit / NULLIF(blks_hit + blks_read, 0), 2)  AS cache_hit_pct,
    deadlocks,
    conflicts,
    temp_files,
    temp_bytes,
    checksum_failures,
    stats_reset
FROM pg_stat_database
WHERE datname IS NOT NULL
ORDER BY xact_commit + xact_rollback DESC;
