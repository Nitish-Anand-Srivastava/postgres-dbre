/*
===============================================================================
SCRIPT NAME:
01_database_size_snapshot.sql

PURPOSE:
Takes a current per-database size snapshot to determine whether the growth is logical at all, or purely at the Aurora volume level.

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
Step 01 of workflow 'storage-and-capacity/unexpected-storage-growth'

RELATED SCRIPTS:
02_largest_tables_snapshot.sql

HOW TO INTERPRET RESULTS:
This is the fork in the investigation. Compare these figures against your last baseline and against CloudWatch VolumeBytesUsed over the same period. If logical size grew in step with the volume, data was written and scripts 02 through 04 will find it. If logical size is flat or falling while the volume climbed, nothing was written -- the space went to WAL retention, temp files, or an in-progress build, and you should jump to scripts 05 through 07. Getting this split right in the first two minutes saves an hour of looking in the wrong place.
===============================================================================
*/

-- Size of every database in the cluster. On Aurora, this reflects logical
-- object size as PostgreSQL reports it; actual billed storage is tracked
-- separately by the Aurora storage layer (see AWS Console/CloudWatch
-- VolumeBytesUsed, not a SQL-visible value) because Aurora storage grows in
-- 10GiB increments and is shared/compressed across the cluster's
-- replicas.
SELECT
    datname,
    pg_size_pretty(pg_database_size(datname))                     AS database_size,
    pg_database_size(datname)                                     AS database_size_bytes
FROM pg_database
WHERE datallowconn
ORDER BY pg_database_size(datname) DESC;
