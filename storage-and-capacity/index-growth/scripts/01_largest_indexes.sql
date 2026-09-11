/*
===============================================================================
SCRIPT NAME:
01_largest_indexes.sql

PURPOSE:
Ranks every index in the database by raw size to establish where index bytes are concentrated.

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
Step 01 of workflow 'storage-and-capacity/index-growth'

RELATED SCRIPTS:
02_index_to_table_size_ratio.sql

HOW TO INTERPRET RESULTS:
This is a starting inventory, not a verdict -- the biggest index on the biggest table is usually entirely legitimate. What you are looking for is an index whose size is disproportionate to its table, or an index name nobody recognizes. Note the totals so you can compare against the table sizes from the table-growth workflow.
===============================================================================
*/

\set top_n 30
SELECT
    n.nspname                                                   AS schema_name,
    t.relname                                                    AS table_name,
    i.relname                                                    AS index_name,
    pg_size_pretty(pg_relation_size(i.oid))                       AS index_size
FROM pg_index ix
JOIN pg_class t ON t.oid = ix.indrelid
JOIN pg_class i ON i.oid = ix.indexrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY pg_relation_size(i.oid) DESC
LIMIT :top_n;
