/*
===============================================================================
SCRIPT NAME:
01_reader_cache_and_load.sql

PURPOSE:
Checks buffer cache hit ratio and current session load directly on the specific reader instance.

AURORA POSTGRESQL VERSION:
Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise)

EXECUTION LOCATION:
Reader instance specifically

SAFETY:
READ ONLY

EXPECTED IMPACT:
Minimal -- reads system catalogs/statistics views only, no table locks beyond a brief catalog lookup.

REQUIRED PRIVILEGES:
Role membership in `pg_monitor` (or `pg_read_all_stats`) is sufficient. No superuser required.

PREREQUISITES:
None beyond CONNECT on the target database.

EXECUTION ORDER:
Step 01 of workflow 'replication-and-ha/reader-performance'

RELATED SCRIPTS:
02_reader_lag_check.sql

HOW TO INTERPRET RESULTS:
confirmed_reader should be true; a low cache_hit_ratio_pct on this specific reader relative to its siblings points to a cold-cache or under-provisioned-instance-class issue for this instance specifically.
===============================================================================
*/

-- Buffer cache hit ratio and active session count for the CURRENT
-- connection's database -- run this connected directly to the specific
-- reader instance under investigation, not the load-balanced reader
-- endpoint, to isolate its individual state.
SELECT
    (SELECT round(100.0 * blks_hit / NULLIF(blks_hit + blks_read, 0), 2)
     FROM pg_stat_database WHERE datname = current_database())          AS cache_hit_ratio_pct,
    (SELECT count(*) FROM pg_stat_activity WHERE state = 'active')      AS active_sessions,
    (SELECT count(*) FROM pg_stat_activity)                             AS total_sessions,
    pg_is_in_recovery()                                                 AS confirmed_reader;
