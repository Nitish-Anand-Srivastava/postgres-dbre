/*
===============================================================================
SCRIPT NAME:
11_temp_file_usage.sql

PURPOSE:
Reports cumulative temporary file creation per database, indicating sorts and hashes spilling to disk.

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
Step 11 of workflow 'database-health/comprehensive-health-check'

RELATED SCRIPTS:
12_index_usage_overview.sql, ../../query-optimization/temp-file-investigation/README.md

HOW TO INTERPRET RESULTS:
Divide temp_bytes by the counting window to get a rate and compare it with the previous run. A steadily climbing rate means work_mem is undersized for the query shapes now running, or that stale statistics are causing the planner to under-estimate rows and pick a memory-starved plan. Temp file I/O on Aurora is served by local instance storage, which is finite and shared with other operations -- large sustained spills can degrade unrelated queries on the same instance.
===============================================================================
*/

-- Cumulative temp file counters per database. A rising temp_bytes rate
-- indicates queries are spilling sorts/hashes/materializations to disk,
-- most often because work_mem is undersized for the actual query shapes
-- running in production, or because statistics are stale and the planner
-- underestimates row counts.
SELECT
    datname,
    temp_files,
    pg_size_pretty(temp_bytes)                                    AS temp_bytes_total,
    stats_reset
FROM pg_stat_database
WHERE datname IS NOT NULL
ORDER BY temp_bytes DESC;
