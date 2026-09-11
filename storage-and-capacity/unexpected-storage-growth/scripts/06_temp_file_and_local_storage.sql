/*
===============================================================================
SCRIPT NAME:
06_temp_file_and_local_storage.sql

PURPOSE:
Checks temporary file usage, which explains local storage growth that never appears in the cluster volume.

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
Step 06 of workflow 'storage-and-capacity/unexpected-storage-growth'

RELATED SCRIPTS:
../temp-file-growth/README.md

HOW TO INTERPRET RESULTS:
This script matters most when CloudWatch shows FreeLocalStorage dropping while VolumeBytesUsed stays flat -- that pattern means temp files on a single instance, not cluster data, and the entire cluster-volume investigation is a dead end. A sharp rise in temp_bytes points at a query spilling sorts or hashes, usually a reporting or reconciliation job running against full history. Follow up in the temp-file-growth workflow for live attribution. Remember these counters are per instance: run this on the instance that is actually reporting low local storage.
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
