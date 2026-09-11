/*
===============================================================================
SCRIPT NAME:
01_target_table_size_and_state.sql

PURPOSE:
Measures the target table precisely, since size and index count are what determine how long any rewriting statement will hold its lock.

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
Step 01 of workflow 'schema-changes/large-table-ddl'

RELATED SCRIPTS:
02_dependent_objects_inventory.sql

HOW TO INTERPRET RESULTS:
total_size_bytes is your rewrite duration proxy and index_count is the multiplier on it, because a rewrite has to rebuild every index as well as the heap. Treat any table above roughly ten gigabytes with a double-digit index count as one where a rewriting statement is simply not an option during trading hours. If n_dead_tup is high and last_autovacuum is stale, the rewrite also has to process all that dead space, so vacuuming first genuinely shortens the lock window. Edit the schema_name and table_name variables at the top for your real target.
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
