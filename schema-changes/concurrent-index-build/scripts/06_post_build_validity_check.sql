/*
===============================================================================
SCRIPT NAME:
06_post_build_validity_check.sql

PURPOSE:
Confirms the finished index is valid and usable, or identifies the INVALID leftover if it was not.

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
Step 06 of workflow 'schema-changes/concurrent-index-build'

RELATED SCRIPTS:
../failed-index-build/README.md

HOW TO INTERPRET RESULTS:
The first result set must not contain your new index. If it does, the build did not complete -- the index is invisible to the planner but still maintained by every write, so it is strictly worse than having no index and must be dropped before any retry. The second result set gives the full index inventory for the target table; confirm your new index appears there with is_valid and is_ready both true, and with the definition you intended. Edit the schema_name and table_name variables at the top for your real target. Finally, check dead tuples on the table over the next day: the build blocked autovacuum for its whole duration, so a long build usually leaves cleanup to catch up on.
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

-- Complete index and constraint inventory for one target table, which is
-- the mandatory pre-flight read before any schema change: it tells you what
-- already exists (so you do not build a redundant index), which indexes back
-- constraints (so you do not attempt to drop one directly), and whether any
-- index is currently INVALID or NOT READY from an earlier failed build.
--
-- Ships with an illustrative default (public.trades) -- edit the \set lines
-- below for your real target. Both branches compare the name only inside a
-- catalog WHERE clause and never cast it to regclass, so this script is
-- safe to run unmodified even when that table does not exist here: it simply
-- returns zero rows.
\set schema_name 'public'
\set table_name 'trades'
SELECT
    'index'                                                     AS object_type,
    i.relname                                                    AS object_name,
    pg_size_pretty(pg_relation_size(i.oid))                       AS object_size,
    ix.indisvalid                                                AS is_valid,
    ix.indisready                                                AS is_ready,
    ix.indisprimary                                              AS is_primary,
    ix.indisunique                                               AS is_unique,
    pg_get_indexdef(ix.indexrelid)                               AS definition
FROM pg_index ix
JOIN pg_class c ON c.oid = ix.indrelid
JOIN pg_class i ON i.oid = ix.indexrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = :'schema_name'
  AND c.relname = :'table_name'
UNION ALL
SELECT
    'constraint',
    con.conname,
    NULL,
    con.convalidated,
    NULL,
    con.contype = 'p',
    con.contype IN ('u', 'p'),
    pg_get_constraintdef(con.oid)
FROM pg_constraint con
JOIN pg_class c ON c.oid = con.conrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = :'schema_name'
  AND c.relname = :'table_name'
ORDER BY object_type, object_name;
