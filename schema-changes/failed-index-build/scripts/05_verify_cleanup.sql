/*
===============================================================================
SCRIPT NAME:
05_verify_cleanup.sql

PURPOSE:
Confirms the leftover is gone and the target table's index inventory is back to a known-good state before any retry.

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
Step 05 of workflow 'schema-changes/failed-index-build'

RELATED SCRIPTS:
../concurrent-index-build/README.md

HOW TO INTERPRET RESULTS:
The first result set should now be empty, or at least should no longer contain the index you dropped. The second gives the full index and constraint inventory for the target table -- confirm every remaining index shows is_valid and is_ready as true, and that nothing you did not intend to touch has changed. Edit the schema_name and table_name variables at the top for your real target. Only once both checks are clean should the build be retried, and only with the failure cause from script 03 actually addressed: retrying with the same session settings and the same blocking transactions present simply produces another leftover and another round of this workflow.
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
