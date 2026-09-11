/*
===============================================================================
SCRIPT NAME:
02_existing_index_inventory.sql

PURPOSE:
Checks whether the proposed access pattern is already covered by an existing index's leading columns.

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
Step 02 of workflow 'schema-changes/add-index-large-table'

RELATED SCRIPTS:
03_write_volume_and_hot_ratio.sql

HOW TO INTERPRET RESULTS:
Read every definition, not just the index names. PostgreSQL uses a multi-column index for queries filtering only on its leading columns, so an existing index on (account_id, executed_at DESC) already serves a query filtering on account_id alone, and adding a single-column index there buys nothing while costing write amplification forever. Count the indexes too: if the table already carries ten or more, the right conversation is an index-set review rather than another addition. Check is_valid and is_ready as well -- a leftover from a previous failed build must be cleaned up before a new build is attempted. Edit the schema_name and table_name variables at the top for your real target.
===============================================================================
*/

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
