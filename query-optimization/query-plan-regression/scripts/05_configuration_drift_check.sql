/*
===============================================================================
SCRIPT NAME:
05_configuration_drift_check.sql

PURPOSE:
Checks planner and memory configuration for drift that could have changed the plan.

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
Step 05 of workflow 'query-optimization/query-plan-regression'

RELATED SCRIPTS:
06_plan_baseline_comparison.md

HOW TO INTERPRET RESULTS:
Focus on three things. Any enable_* parameter set to off -- these are diagnostic switches and a forgotten one from a past incident will distort plans indefinitely. The source column: a value that came from a session-level SET means the application is overriding the parameter group at connection time, so the plan depends on which application connects. And pending_restart being true means a parameter-group change has been made but is not yet active, so the regression may correlate with a later reboot or failover rather than with the change itself.
===============================================================================
*/

-- Planner and executor configuration: the inputs that decide which plan
-- shape PostgreSQL chooses for a given query. Differences here between a
-- staging environment and production explain a surprising share of
-- "the same query has a different plan in production" reports.
--
-- reset_val is the value a new session would get; setting is the value in
-- THIS session (an application that issues SET at connection time can be
-- running with something entirely different from the parameter group).
-- source shows where the value came from, and pending_restart flags a
-- parameter-group change that has been applied but not yet activated by
-- the required reboot.
SELECT
    name,
    setting,
    unit,
    boot_val                                                     AS engine_default,
    reset_val                                                    AS new_session_value,
    source,
    context,
    pending_restart,
    short_desc
FROM pg_settings
WHERE name IN (
    'work_mem', 'hash_mem_multiplier', 'maintenance_work_mem', 'temp_buffers',
    'shared_buffers', 'effective_cache_size', 'effective_io_concurrency',
    'random_page_cost', 'seq_page_cost', 'cpu_tuple_cost',
    'cpu_index_tuple_cost', 'cpu_operator_cost',
    'default_statistics_target', 'from_collapse_limit', 'join_collapse_limit',
    'geqo', 'geqo_threshold', 'plan_cache_mode', 'jit', 'jit_above_cost',
    'enable_seqscan', 'enable_indexscan', 'enable_indexonlyscan',
    'enable_bitmapscan', 'enable_nestloop', 'enable_hashjoin',
    'enable_mergejoin', 'enable_memoize', 'enable_sort',
    'enable_incremental_sort', 'enable_partitionwise_join',
    'enable_partitionwise_aggregate',
    'max_parallel_workers_per_gather', 'parallel_setup_cost',
    'parallel_tuple_cost', 'track_io_timing', 'log_temp_files',
    'temp_file_limit'
)
ORDER BY name;

-- Snapshot of the settings that most commonly explain performance and
-- concurrency behavior differences between environments. On Aurora, most of
-- these are controlled by the DB cluster parameter group (values shared by
-- all instances) or the DB instance parameter group (writer/reader-specific
-- overrides), not postgresql.conf -- use the AWS Console/CLI
-- (describe-db-cluster-parameters / describe-db-parameters) to change them,
-- not ALTER SYSTEM, which Aurora does not support for most parameters.
SELECT
    name,
    setting,
    unit,
    category,
    short_desc,
    context
FROM pg_settings
WHERE name IN (
    'max_connections', 'shared_buffers', 'work_mem', 'maintenance_work_mem',
    'effective_cache_size', 'autovacuum', 'autovacuum_max_workers',
    'autovacuum_naptime', 'autovacuum_vacuum_cost_limit',
    'autovacuum_freeze_max_age', 'autovacuum_multixact_freeze_max_age',
    'checkpoint_timeout', 'max_wal_size', 'statement_timeout',
    'idle_in_transaction_session_timeout', 'lock_timeout',
    'log_lock_waits', 'deadlock_timeout', 'track_io_timing',
    'shared_preload_libraries', 'random_page_cost', 'effective_io_concurrency'
)
ORDER BY name;
