/*
===============================================================================
SCRIPT NAME:
04_database_and_cluster_inventory.sql

PURPOSE:
Provides a basic inventory of every non-template database in the cluster,
including size and connection limit, as a starting point for capacity and
"what else is running here" awareness before a focused investigation.

AURORA POSTGRESQL VERSION:
17+

EXECUTION LOCATION:
Any instance (writer or reader) -- pg_database and database size are
identical across all instances since storage is shared.

SAFETY:
READ ONLY

EXPECTED IMPACT:
Low -- pg_database_size() reads size metadata; on a very large database
this can take a brief moment but does not block other sessions.

REQUIRED PRIVILEGES:
CONNECT privilege on each database is not required to see it listed here
(pg_database is readable cluster-wide), but pg_database_size() requires
either CONNECT privilege on that database or membership in pg_monitor /
pg_read_all_stats to see a non-null size for databases you cannot connect
to.

PREREQUISITES:
None.

EXECUTION ORDER:
Step 04 of common/scripts

RELATED SCRIPTS:
01_postgres_and_aurora_version.sql

HOW TO INTERPRET RESULTS:
`database_size` is a point-in-time snapshot, not a growth rate -- for
trend analysis see storage-and-capacity/database-growth/ once populated.
`datconnlimit = -1` means no per-database connection limit is configured;
compare `datconnlimit` (if set) against the cluster-wide `max_connections`
setting when investigating connection exhaustion.
===============================================================================
*/

SELECT
    d.datname                                    AS database_name,
    pg_size_pretty(pg_database_size(d.datname))  AS database_size_pretty,
    pg_database_size(d.datname)                  AS database_size_bytes,
    d.datconnlimit                               AS connection_limit,
    d.datallowconn                               AS allows_connections,
    d.datistemplate                              AS is_template
FROM pg_database d
WHERE d.datistemplate = false
ORDER BY pg_database_size(d.datname) DESC;
