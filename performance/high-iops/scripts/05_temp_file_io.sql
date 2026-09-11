/*
===============================================================================
SCRIPT NAME:
05_temp_file_io.sql

PURPOSE:
Checks temp file generation, which directly consumes read/write IOPS for spilled sorts/hashes.

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
Step 05 of workflow 'performance/high-iops'

RELATED SCRIPTS:
../../query-optimization/temp-file-investigation/README.md

HOW TO INTERPRET RESULTS:
A high or rapidly growing temp_bytes total indicates work_mem is undersized for current query shapes; see query-optimization/temp-file-investigation for the query-level drill-down.
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
