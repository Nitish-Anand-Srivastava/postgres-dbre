/*
===============================================================================
SCRIPT NAME:
01_invalid_indexes.sql

PURPOSE:
Finds every INVALID index in the database and quantifies the storage each one is wasting.

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
Step 01 of workflow 'schema-changes/failed-index-build'

RELATED SCRIPTS:
02_builds_currently_running.sql

HOW TO INTERPRET RESULTS:
Every row here is pure cost: the planner ignores the index completely, yet every insert and non-HOT update on the table still maintains it and every vacuum still processes it. Read the index_definition column to identify what the original build was trying to achieve, and note any name ending in _ccnew, _ccnew1 or similar -- that is the signature of an interrupted REINDEX CONCURRENTLY rather than a failed create, and the original index is still present and valid alongside it. Several INVALID indexes with similar definitions on one table means the build has been retried repeatedly without cleanup; drop all of them before the next attempt. Do not drop anything until script 02 confirms no build is in progress.
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
