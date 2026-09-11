/*
===============================================================================
SCRIPT NAME:
05_join_strategy_settings.sql

PURPOSE:
Reviews the planner settings that govern join strategy selection and repeated-lookup caching.

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
Step 05 of workflow 'query-optimization/nested-loop-problems'

RELATED SCRIPTS:
06_confirm_nested_loop_safely.md

HOW TO INTERPRET RESULTS:
Confirm enable_nestloop, enable_hashjoin, and enable_mergejoin are all on -- any of them left off from a previous diagnostic session forces the planner into a corner. Check enable_memoize (on by default since PostgreSQL 14): it caches inner-side results for repeated keys and substantially reduces the damage of a loop with low key cardinality. Finally, effective_cache_size and random_page_cost directly determine how cheap the planner believes each repeated index lookup to be; defaults that describe a small local-disk server systematically distort that judgement on Aurora.
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
