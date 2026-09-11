/*
===============================================================================
SCRIPT NAME:
05_largest_indexes.sql

PURPOSE:
Ranks individual indexes by size so that over-indexing is visible independently of the tables that own the indexes.

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
Step 05 of workflow 'storage-and-capacity/database-growth'

RELATED SCRIPTS:
../index-growth/README.md

HOW TO INTERPRET RESULTS:
An individual index approaching or exceeding the size of its own table is worth immediate scrutiny -- it is usually either a multi-column index whose leading column is already covered by another index, or an index on a wide text/JSON column that should be an expression or partial index instead. Cross-check anything that looks suspicious against the index-growth workflow before proposing a drop; size alone is never sufficient evidence.
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
