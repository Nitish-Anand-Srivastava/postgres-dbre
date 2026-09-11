/*
===============================================================================
SCRIPT NAME:
04_sort_and_join_settings.sql

PURPOSE:
Reviews the settings that govern merge join selection, sorting, and incremental sort.

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
Step 04 of workflow 'query-optimization/merge-join-analysis'

RELATED SCRIPTS:
05_inspect_merge_join_plan.md

HOW TO INTERPRET RESULTS:
Confirm enable_mergejoin and enable_sort are on, and note whether enable_incremental_sort is on (it is by default from PostgreSQL 13): incremental sort is what lets a partially matching index still avoid a full sort. work_mem determines whether the feeding sorts stay in memory. random_page_cost and effective_io_concurrency determine how expensive the planner believes the ordered index scan to be, and defaults tuned for local spinning disks systematically discourage the ordered scan that would make merge join the better plan on Aurora.
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
