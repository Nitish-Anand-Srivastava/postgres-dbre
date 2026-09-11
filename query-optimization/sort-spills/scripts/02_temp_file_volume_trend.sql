/*
===============================================================================
SCRIPT NAME:
02_temp_file_volume_trend.sql

PURPOSE:
Measures cluster-wide temporary file volume to judge whether spilling is systemic.

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
Step 02 of workflow 'query-optimization/sort-spills'

RELATED SCRIPTS:
03_sort_memory_settings.sql, ../temp-file-investigation/README.md

HOW TO INTERPRET RESULTS:
Convert temp_bytes into a rate using the counting window and compare it against previous health checks. A steadily rising rate with an unchanged workload is a capacity signal: data volumes have crossed the point where previously in-memory sorts no longer fit, and the memory configuration needs to grow with the data. A sudden step change points at a specific new query or deployment instead.
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
