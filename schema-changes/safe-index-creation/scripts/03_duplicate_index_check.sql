/*
===============================================================================
SCRIPT NAME:
03_duplicate_index_check.sql

PURPOSE:
Checks the database for structurally duplicate indexes, so a new index is not added to a table that already has a redundancy problem.

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
Step 03 of workflow 'schema-changes/safe-index-creation'

RELATED SCRIPTS:
04_ddl_safety_settings.sql

HOW TO INTERPRET RESULTS:
If the target table already appears here, resolve the existing duplication before adding anything new -- otherwise you are compounding write amplification on a table that is already paying for it twice. Duplicates most commonly arise from an ORM migration and a hand-written migration creating the same index under different names, which is exactly the situation a new manual index build risks creating again. Nothing here should be dropped as part of this workflow; route it through the drop-index-safely runbook.
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
