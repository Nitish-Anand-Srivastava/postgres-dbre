/*
===============================================================================
SCRIPT NAME:
05_target_table_indexes_and_statistics.sql

PURPOSE:
Inventories the indexes and statistics freshness of the table the statement touches.

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
Step 05 of workflow 'query-optimization/analyze-query-plan'

RELATED SCRIPTS:
06_capture_plan_safely.md, ../stale-statistics/README.md

HOW TO INTERPRET RESULTS:
Read the index list against the statement's WHERE, JOIN, and ORDER BY clauses: the question is not 'are there indexes' but 'is there an index whose leading columns match this predicate'. An index with idx_scan at zero while the statement runs constantly means the planner is rejecting it -- usually because of a type mismatch, a function wrapped around the column, or statistics that make a sequential scan look cheaper. Then check statistics freshness for the same table: a high n_mod_since_analyze means every estimate in the plan is built on an outdated picture.
===============================================================================
*/

-- Every index on one specific table, with its definition and its real
-- usage counters. Edit the two \set lines to name the table you are
-- investigating.
--
-- The relation name is only ever compared inside a catalog WHERE clause
-- here (never used as a FROM target and never cast with ::regclass), so a
-- name that does not exist simply returns zero rows instead of raising
-- "relation does not exist".
\set schema_name 'public'
\set table_name 'orders'
SELECT
    n.nspname                                                    AS schema_name,
    c.relname                                                    AS table_name,
    i.relname                                                    AS index_name,
    pg_size_pretty(pg_relation_size(i.oid))                       AS index_size,
    ix.indisunique,
    ix.indisprimary,
    ix.indisvalid,
    s.idx_scan,
    s.idx_tup_read,
    s.idx_tup_fetch,
    s.last_idx_scan,
    pg_get_indexdef(ix.indexrelid)                                AS index_definition
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_index ix ON ix.indrelid = c.oid
JOIN pg_class i ON i.oid = ix.indexrelid
LEFT JOIN pg_stat_all_indexes s ON s.indexrelid = ix.indexrelid
WHERE n.nspname = :'schema_name'
  AND c.relname = :'table_name'
ORDER BY pg_relation_size(i.oid) DESC;

-- Tables whose planner statistics may be stale relative to how much the
-- table has changed since the last ANALYZE. n_mod_since_analyze counts
-- inserts+updates+deletes since the last analyze; a large value relative to
-- table size means the planner's row estimates (and therefore its join
-- order / index choice) can be significantly wrong.
\set top_n 30
SELECT
    schemaname                                                  AS schema_name,
    relname                                                     AS table_name,
    n_live_tup,
    n_mod_since_analyze,
    round(100.0 * n_mod_since_analyze / NULLIF(n_live_tup, 0), 2) AS pct_modified_since_analyze,
    last_analyze,
    last_autoanalyze
FROM pg_stat_all_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY pct_modified_since_analyze DESC NULLS LAST
LIMIT :top_n;
