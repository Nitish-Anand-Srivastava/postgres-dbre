/*
===============================================================================
SCRIPT NAME:
02_cache_warmup_progress.sql

PURPOSE:
Tracks buffer cache hit ratio to quantify and monitor cold-cache recovery progress.

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
Step 02 of workflow 'performance/performance-after-failover'

RELATED SCRIPTS:
03_reconnect_storm_check.sql

HOW TO INTERPRET RESULTS:
An improving trend across repeated runs is expected and healthy; a flat, persistently low ratio well past a typical warm-up window (minutes, not tens of minutes, for most working sets) warrants pivoting to sudden-performance-degradation.
===============================================================================
*/

-- Buffer cache hit ratio for the current database. Re-run this every few
-- minutes after a failover: a steadily improving ratio confirms normal,
-- self-resolving cache warm-up rather than a separate ongoing problem.
SELECT
    datname,
    blks_hit,
    blks_read,
    round(100.0 * blks_hit / NULLIF(blks_hit + blks_read, 0), 3) AS cache_hit_ratio_pct
FROM pg_stat_database
WHERE datname = current_database();
