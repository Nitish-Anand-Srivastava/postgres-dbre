/*
===============================================================================
SCRIPT NAME:
02_duplicate_index_candidates.sql

PURPOSE:
Finds structurally identical indexes, which are the safest possible drop candidates.

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
Step 02 of workflow 'schema-changes/drop-index-safely'

RELATED SCRIPTS:
03_index_role_and_drop_verdict.sql

HOW TO INTERPRET RESULTS:
Start your cleanup here rather than with the unused list. Anything reported is wasted storage and wasted write overhead by definition: the surviving copy serves exactly the same queries, so the planner cannot regress and the usual month-end-reconciliation worry does not apply. Keep the copy with the clearer, more descriptive name and the longer usage history from script 03, and drop the other. Duplicates most commonly arise when an ORM migration and a hand-written migration create the same index under different names, so expect to find them in pairs on tables that several teams have extended.
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
