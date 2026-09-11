/*
===============================================================================
SCRIPT NAME:
03_duplicate_indexes.sql

PURPOSE:
Finds structurally duplicate indexes on the same table.

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
Step 03 of workflow 'query-optimization/inefficient-index-usage'

RELATED SCRIPTS:
04_index_scan_efficiency.sql, ../../tables-and-indexes/duplicate-indexes/README.md

HOW TO INTERPRET RESULTS:
True duplicates -- identical column lists, access method, and predicate -- are unambiguous overhead: identical storage, identical write cost, no additional query benefit. They usually arise from a migration that created an index the schema already had under a different name. Removing them is among the safest index changes available, though it is still a schema change and still uses DROP INDEX CONCURRENTLY.
===============================================================================
*/

-- Indexes on the same table with identical column lists (indkey), access
-- method, and expression/predicate signature -- true structural duplicates
-- that waste storage and add write overhead without any query benefit.
-- Compares the human-readable index definition rather than raw indkey
-- arrays so expression indexes and partial indexes are also caught
-- correctly.
SELECT
    n.nspname                                                    AS schema_name,
    c.relname                                                    AS table_name,
    array_agg(i.relname ORDER BY i.relname)                       AS duplicate_index_names,
    min(regexp_replace(pg_get_indexdef(ix.indexrelid), 'INDEX [^ ]+ ', 'INDEX ', 1, 1)) AS normalized_definition,
    count(*)                                                     AS duplicate_count,
    pg_size_pretty(sum(pg_relation_size(i.oid)))                  AS combined_size
FROM pg_index ix
JOIN pg_class c ON c.oid = ix.indrelid
JOIN pg_class i ON i.oid = ix.indexrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
GROUP BY n.nspname, c.relname, ix.indrelid,
         regexp_replace(pg_get_indexdef(ix.indexrelid), 'INDEX [^ ]+ ', 'INDEX ', 1, 1)
HAVING count(*) > 1
ORDER BY combined_size DESC;
