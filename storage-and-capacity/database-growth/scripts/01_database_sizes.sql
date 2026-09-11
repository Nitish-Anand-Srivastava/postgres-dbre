/*
===============================================================================
SCRIPT NAME:
01_database_sizes.sql

PURPOSE:
Ranks every connectable database in the cluster by logical size to confirm which database the growth actually lives in.

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
Step 01 of workflow 'storage-and-capacity/database-growth'

RELATED SCRIPTS:
02_schema_size_breakdown.sql

HOW TO INTERPRET RESULTS:
Expect one dominant application database. If a database you did not expect (a staging copy, an old migration target, a forgotten reporting database) appears near the top, that is your finding -- confirm ownership before anything else. Note that the sum of these figures will be smaller than the CloudWatch VolumeBytesUsed figure for the cluster; the difference is WAL, temp space, free space map, and volume Aurora allocated previously and never released.
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
