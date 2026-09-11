/*
===============================================================================
SCRIPT NAME:
01_temp_file_volume_by_database.sql

PURPOSE:
Quantifies cumulative temporary file volume and rate per database.

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
Step 01 of workflow 'query-optimization/temp-file-investigation'

RELATED SCRIPTS:
02_statements_producing_temp_files.sql

HOW TO INTERPRET RESULTS:
Divide temp_bytes by the counting window for a bytes-per-second rate, and temp_files by the same window for a files-per-second rate. Together they distinguish many small spills (typical of a high-frequency statement with a slightly undersized work_mem) from a few enormous ones (typical of a report or export). Both need fixing, but the first one is the one silently taxing the trading path.
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
