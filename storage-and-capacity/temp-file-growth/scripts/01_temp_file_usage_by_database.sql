/*
===============================================================================
SCRIPT NAME:
01_temp_file_usage_by_database.sql

PURPOSE:
Reports cumulative temporary file count and volume per database to establish scale and locate the responsible database.

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
Step 01 of workflow 'storage-and-capacity/temp-file-growth'

RELATED SCRIPTS:
02_memory_and_temp_settings.sql

HOW TO INTERPRET RESULTS:
Convert this into a rate before judging it: divide temp_bytes by the elapsed time since stats_reset to get bytes per hour, then compare that against the instance's FreeLocalStorage headroom in CloudWatch. A few hundred megabytes a day on a busy analytical database is routine; tens of gigabytes an hour on the OLTP database that also serves order placement is not. Remember these counters are per instance and reset on failover, so a low number immediately after an Aurora failover means nothing.
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
