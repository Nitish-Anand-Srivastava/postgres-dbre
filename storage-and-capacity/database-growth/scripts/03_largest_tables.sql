/*
===============================================================================
SCRIPT NAME:
03_largest_tables.sql

PURPOSE:
Ranks individual relations by total size (heap plus indexes plus TOAST) -- the definitive list of what is consuming the volume.

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
Step 03 of workflow 'storage-and-capacity/database-growth'

RELATED SCRIPTS:
04_table_size_components.sql

HOW TO INTERPRET RESULTS:
The distribution matters more than the absolute numbers: storage growth is nearly always concentrated, so expect the top 5-10 relations to account for the large majority of the database. Those relations, and only those, are worth remediation effort. A partitioned parent shows a total_size of 0 here because its storage lives in its partitions -- if you see many similarly-named relations with a date suffix, you are looking at a partitioned table and should evaluate it as a whole.
===============================================================================
*/

-- Largest tables in the current database by total size (heap + indexes +
-- TOAST), which is what actually matters for storage capacity planning and
-- I/O footprint.
\set top_n 30
SELECT
    n.nspname                                                   AS schema_name,
    c.relname                                                   AS table_name,
    pg_size_pretty(pg_relation_size(c.oid))                       AS heap_size,
    pg_size_pretty(pg_indexes_size(c.oid))                        AS index_size,
    pg_size_pretty(pg_total_relation_size(c.oid))                 AS total_size,
    c.reltuples::bigint                                          AS estimated_row_count
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY pg_total_relation_size(c.oid) DESC
LIMIT :top_n;
