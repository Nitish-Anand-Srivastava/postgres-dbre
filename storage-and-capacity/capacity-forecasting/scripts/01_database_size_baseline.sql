/*
===============================================================================
SCRIPT NAME:
01_database_size_baseline.sql

PURPOSE:
Records the current per-database size baseline that every projection in this workflow starts from.

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
Step 01 of workflow 'storage-and-capacity/capacity-forecasting'

RELATED SCRIPTS:
02_relation_size_baseline.sql

HOW TO INTERPRET RESULTS:
Record these figures with a timestamp in the forecast document, not just in your terminal. Also record the current CloudWatch VolumeBytesUsed alongside them and note the gap -- that gap is space Aurora has allocated and will never release, and tracking how it widens over time is itself a useful capacity signal that no SQL query can give you.
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
