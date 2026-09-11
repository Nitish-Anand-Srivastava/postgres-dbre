/*
===============================================================================
SCRIPT NAME:
01_sql_side_capacity_and_load_snapshot.sql

PURPOSE:
One-row snapshot of the SQL-visible counterparts to the most commonly alarmed-on Aurora CloudWatch metrics.

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
Step 01 of workflow 'observability/cloudwatch'

RELATED SCRIPTS:
02_replication_lag_sql_companion.sql

HOW TO INTERPRET RESULTS:
Compare pct_connections_used against CloudWatch's DatabaseConnections/max_connections, cache_hit_pct_all_databases against BufferCacheHitRatio, and pct_forced_checkpoints as a proxy for rising DiskQueueDepth/IOPS pressure. total_logical_database_size is not the same number as VolumeBytesUsed (see Aurora notes) but its trend should move in the same direction.
===============================================================================
*/

-- One-row snapshot of the SQL-visible counterparts to the most commonly
-- alarmed-on Aurora CloudWatch metrics, for direct comparison against the
-- CloudWatch console/API when investigating an alarm. This is a proxy, not
-- a replacement: CloudWatch's data comes from the hypervisor/engine level
-- and storage layer and is authoritative for anything billing- or
-- infrastructure-related (actual VolumeBytesUsed, actual CPUUtilization);
-- this query shows what PostgreSQL itself can see, which is what usually
-- explains *why* a CloudWatch metric moved.
SELECT
    (SELECT count(*) FROM pg_stat_activity)                                   AS current_connections,
    (SELECT setting::int FROM pg_settings WHERE name = 'max_connections')     AS max_connections,
    round(
        100.0 * (SELECT count(*) FROM pg_stat_activity) /
        NULLIF((SELECT setting::numeric FROM pg_settings WHERE name = 'max_connections'), 0),
        2
    )                                                                          AS pct_connections_used,
    round(
        100.0 * sum(blks_hit) / NULLIF(sum(blks_hit) + sum(blks_read), 0), 2
    )                                                                          AS cache_hit_pct_all_databases,
    (SELECT round(100.0 * num_requested / NULLIF(num_timed + num_requested, 0), 2)
     FROM pg_stat_checkpointer)                                               AS pct_forced_checkpoints,
    pg_size_pretty(sum(pg_database_size(datname)))                            AS total_logical_database_size,
    sum(temp_bytes)                                                           AS total_temp_bytes_since_reset
FROM pg_stat_database
WHERE datname IS NOT NULL;
