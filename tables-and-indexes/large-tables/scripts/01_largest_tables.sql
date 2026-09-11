/*
===============================================================================
SCRIPT NAME:
01_largest_tables.sql

PURPOSE:
Lists the largest tables by total size.

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
Step 01 of workflow 'tables-and-indexes/large-tables'

RELATED SCRIPTS:
02_largest_indexes.sql

HOW TO INTERPRET RESULTS:
The top entries here are your primary candidates for partitioning/archiving investigation.
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
