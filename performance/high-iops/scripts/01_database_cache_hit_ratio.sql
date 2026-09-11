/*
===============================================================================
SCRIPT NAME:
01_database_cache_hit_ratio.sql

PURPOSE:
Computes the buffer cache hit ratio per database as a proxy for how much read traffic is reaching storage.

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
Step 01 of workflow 'performance/high-iops'

RELATED SCRIPTS:
02_top_io_generating_queries.sql

HOW TO INTERPRET RESULTS:
A low or declining cache hit ratio, especially trending downward over weeks, indicates the working set has outgrown available memory -- correlate with table growth before assuming an instance-class change is required.
===============================================================================
*/

-- Buffer cache hit ratio per database. A ratio consistently below ~99% for
-- an OLTP workload is a meaningful signal that the working set no longer
-- fits comfortably in memory.
SELECT
    datname,
    blks_hit,
    blks_read,
    round(100.0 * blks_hit / NULLIF(blks_hit + blks_read, 0), 3) AS cache_hit_ratio_pct,
    stats_reset
FROM pg_stat_database
WHERE datname IS NOT NULL
ORDER BY cache_hit_ratio_pct ASC NULLS LAST;
