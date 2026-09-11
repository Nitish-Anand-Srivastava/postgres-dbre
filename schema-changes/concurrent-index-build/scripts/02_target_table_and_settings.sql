/*
===============================================================================
SCRIPT NAME:
02_target_table_and_settings.sql

PURPOSE:
Confirms the target table's size and the timeout settings that could kill the build mid-flight.

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
Step 02 of workflow 'schema-changes/concurrent-index-build'

RELATED SCRIPTS:
03_concurrent_index_build_runbook.md

HOW TO INTERPRET RESULTS:
Two things must be checked here before the build starts. First, total_size_bytes sets your duration expectation -- a concurrent build makes two passes plus two waits, so budget roughly two to three times a plain build. Second, statement_timeout and transaction_timeout must either be zero or comfortably longer than that expectation for the session running the build: a timeout firing mid-build aborts it and leaves an INVALID index behind, which is the most avoidable failure mode in this entire workflow. Also confirm maintenance_work_mem is generous enough that the build's sort does not spill to local storage, and remember to check for role-level and database-level timeout defaults, not just the cluster parameter group.
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

-- The settings that determine how a DDL statement behaves when it cannot
-- get its lock immediately, and how much memory/parallelism an index build
-- gets. Always confirm these BEFORE issuing DDL against a busy production
-- table: a DDL statement with no lock_timeout that queues behind a
-- long-running transaction will itself block every subsequent query on the
-- table, converting a single slow statement into a full application outage.
--
-- On Aurora these are set through the DB cluster/instance parameter group,
-- not postgresql.conf; `source` tells you whether the current value came
-- from the parameter group (configuration file), a session-level SET, or
-- the built-in default.
SELECT
    name,
    setting,
    unit,
    context,
    source,
    short_desc
FROM pg_settings
WHERE name IN (
    'lock_timeout', 'statement_timeout', 'transaction_timeout',
    'idle_in_transaction_session_timeout', 'deadlock_timeout',
    'log_lock_waits', 'maintenance_work_mem',
    'max_parallel_maintenance_workers', 'max_locks_per_transaction',
    'default_transaction_read_only', 'default_statistics_target'
)
ORDER BY name;
