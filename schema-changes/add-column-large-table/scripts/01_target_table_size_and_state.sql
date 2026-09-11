/*
===============================================================================
SCRIPT NAME:
01_target_table_size_and_state.sql

PURPOSE:
Measures the target table so the cost of the rewriting form is understood in concrete terms before a form is chosen.

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
Step 01 of workflow 'schema-changes/add-column-large-table'

RELATED SCRIPTS:
02_existing_column_inventory.sql

HOW TO INTERPRET RESULTS:
This number only matters if the statement turns out to be a rewriting one -- but that is exactly why it should be read first, because an abstract 'it might rewrite' does not change behavior while 'it will hold an exclusive lock on this table for ninety minutes' does. Multiply your intuition by index_count, since a rewrite rebuilds every index as well as the heap. Any result above a few minutes means the volatile-default and generated-column forms are off the table entirely and the runbook's split pattern is mandatory. Edit the schema_name and table_name variables at the top for your real target.
===============================================================================
*/

-- Size, row estimate, and maintenance state for a single target table --
-- the numbers that determine how long a rewriting DDL statement will hold
-- its lock, and therefore whether the operation can be done directly or
-- needs the online (build-alongside-and-swap) pattern instead.
--
-- Ships with an illustrative default (public.trades); edit the \set lines
-- below for your real target. to_regclass() is used throughout rather than
-- a ::regclass cast, because a cast raises "relation does not exist" and
-- aborts the statement outright when the name is absent, whereas
-- to_regclass() simply returns NULL and lets the guard print guidance.
\set schema_name 'public'
\set table_name 'trades'
SELECT to_regclass(:'schema_name' || '.' || :'table_name') IS NOT NULL
                                                             AS target_table_exists
\gset

\if :target_table_exists
SELECT
    :'schema_name' || '.' || :'table_name'                        AS target_table,
    pg_size_pretty(pg_relation_size(
        to_regclass(:'schema_name' || '.' || :'table_name')))     AS heap_size,
    pg_size_pretty(pg_indexes_size(
        to_regclass(:'schema_name' || '.' || :'table_name')))     AS index_size,
    pg_size_pretty(pg_total_relation_size(
        to_regclass(:'schema_name' || '.' || :'table_name')))     AS total_size,
    pg_total_relation_size(
        to_regclass(:'schema_name' || '.' || :'table_name'))      AS total_size_bytes,
    s.n_live_tup,
    s.n_dead_tup,
    s.n_mod_since_analyze,
    s.last_vacuum,
    s.last_autovacuum,
    s.last_analyze,
    s.last_autoanalyze,
    (SELECT count(*) FROM pg_index ix
      WHERE ix.indrelid = to_regclass(:'schema_name' || '.' || :'table_name'))
                                                                 AS index_count
FROM pg_stat_all_tables s
WHERE s.relid = to_regclass(:'schema_name' || '.' || :'table_name');
\else
SELECT
    'Table ' || :'schema_name' || '.' || :'table_name' || ' does not exist '
    'in this database. Edit the schema_name/table_name \set lines at the top '
    'of this script to point at the real table you intend to change, then '
    're-run. Realistic targets on an exchange platform include public.orders, '
    'public.trades, public.ledger_entries, public.wallets, public.deposits '
    'and public.withdrawals.'                                     AS notice;
\endif
