/*
===============================================================================
SCRIPT NAME:
06_single_table_deep_dive.sql

PURPOSE:
Drills into one named table for exact size, live/dead row estimates, and vacuum/analyze recency before committing to a remediation path.

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
Step 06 of workflow 'storage-and-capacity/table-growth'

RELATED SCRIPTS:
../../tables-and-indexes/large-tables/README.md

HOW TO INTERPRET RESULTS:
Read last_autovacuum and last_autoanalyze first: if both are stale, n_live_tup and n_dead_tup are stale too and nothing else on this row can be trusted. A healthy large table shows recent autovacuum activity, a dead tuple count well under 20% of live tuples, and an index_count you can justify one index at a time. An index_count in double digits on a write-heavy exchange table is itself the finding. Edit the schema_name and table_name variables at the top to point at your real target -- the shipped default is illustrative and guarded, so running it unmodified prints guidance instead of failing.
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
