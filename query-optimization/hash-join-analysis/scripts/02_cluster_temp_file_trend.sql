/*
===============================================================================
SCRIPT NAME:
02_cluster_temp_file_trend.sql

PURPOSE:
Measures cluster-wide temporary file volume to judge whether spilling is systemic or isolated.

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
Step 02 of workflow 'query-optimization/hash-join-analysis'

RELATED SCRIPTS:
03_memory_and_spill_settings.sql, ../temp-file-investigation/README.md

HOW TO INTERPRET RESULTS:
Divide temp_bytes by the counting window to get a rate, and compare it across health checks. A steadily rising rate with an unchanged workload means data volumes have crossed the threshold where previously in-memory operations now spill -- a capacity signal about memory sizing, not a query defect. A sudden step change points at a specific deployment or a new report.
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
