/*
===============================================================================
SCRIPT NAME:
04_ordering_index_coverage.sql

PURPOSE:
Checks whether an index could supply the required ordering and remove the sort entirely.

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
Step 04 of workflow 'query-optimization/sort-spills'

RELATED SCRIPTS:
05_size_sort_memory_safely.md, ../merge-join-analysis/README.md

HOW TO INTERPRET RESULTS:
Read each index definition against the statement's ORDER BY, GROUP BY, and DISTINCT clauses, including sort direction and NULLS ordering. An index on (account_id, created_at DESC) can serve ORDER BY created_at DESC for a single account without any sort at all; an index on (created_at) alone cannot serve ORDER BY account_id, created_at. Where a partial prefix matches, PostgreSQL 13+ can use an Incremental Sort, which is already a large improvement and hints that extending the index would remove the sort completely.
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
