/*
===============================================================================
SCRIPT NAME:
06_invalid_index_waste.sql

PURPOSE:
Finds indexes left INVALID by an interrupted build, which consume full storage while being unusable by the planner.

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
Step 06 of workflow 'storage-and-capacity/index-growth'

RELATED SCRIPTS:
../../schema-changes/failed-index-build/README.md

HOW TO INTERPRET RESULTS:
Every row here is pure waste: the planner ignores an INVALID index entirely, but every write still maintains it and every vacuum still processes it. The usual cause is a concurrent index build that was cancelled, hit a statement timeout, or died with its session. Drop these unconditionally via the failed-index-build runbook, and only rebuild if the original query need still exists -- often it does not, because someone already solved the problem another way after the build failed.
===============================================================================
*/

-- Indexes left in an INVALID state, almost always because a previous
-- CREATE INDEX CONCURRENTLY or REINDEX CONCURRENTLY failed partway through
-- (a killed session, statement_timeout, or deadlock). Invalid indexes are
-- not used by the planner but still consume storage and slow down writes,
-- so they should be dropped and, if needed, recreated concurrently.
SELECT
    n.nspname                                                   AS schema_name,
    c.relname                                                   AS table_name,
    i.relname                                                   AS index_name,
    pg_size_pretty(pg_relation_size(i.oid))                      AS wasted_size,
    pg_get_indexdef(ix.indexrelid)                               AS index_definition
FROM pg_index ix
JOIN pg_class c ON c.oid = ix.indrelid
JOIN pg_class i ON i.oid = ix.indexrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE NOT ix.indisvalid
ORDER BY pg_relation_size(i.oid) DESC;
