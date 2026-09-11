/*
===============================================================================
SCRIPT NAME:
05_duplicate_index_candidates.sql

PURPOSE:
Finds structurally identical indexes on the same table -- the highest-confidence, lowest-risk drop candidates available.

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
Step 05 of workflow 'storage-and-capacity/index-growth'

RELATED SCRIPTS:
../../tables-and-indexes/duplicate-indexes/README.md

HOW TO INTERPRET RESULTS:
Anything reported here is wasted storage and wasted write overhead by definition: the duplicate serves exactly the same queries as the copy you keep, so the planner cannot regress. Keep the copy with the clearer name and the longer usage history from script 03, and drop the other through the drop-index-safely runbook. Duplicates most often come from an ORM migration and a hand-written migration creating the same index under different names.
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
