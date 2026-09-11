/*
===============================================================================
SCRIPT NAME:
03_memory_and_spill_settings.sql

PURPOSE:
Reviews the memory settings that determine whether a hash join stays in memory or spills.

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
Step 03 of workflow 'query-optimization/hash-join-analysis'

RELATED SCRIPTS:
04_statistics_freshness_on_join_inputs.sql

HOW TO INTERPRET RESULTS:
Effective hash memory is roughly work_mem multiplied by hash_mem_multiplier, per node and per parallel worker. Multiply that by max_parallel_workers_per_gather and by the number of hash nodes in the plan to see the true worst-case footprint of a single statement, then by the number of concurrent connections running it to see the instance-level exposure. If log_temp_files is -1, temporary file creation is not being logged at all and spills can only be seen after the fact through these counters.
===============================================================================
*/

-- The memory settings that decide whether a sort, hash, or materialize
-- step stays in RAM or spills to a temporary file on local instance
-- storage, shown both as the value this session would get and as the value
-- currently in effect for this session.
--
-- work_mem is per sort/hash NODE, not per query and not per connection: a
-- single query with several sorts and hash joins, running in parallel
-- across workers, can consume a multiple of work_mem simultaneously. That
-- is why raising it globally on a high-connection exchange writer is
-- dangerous, and why the safe experiment is a session-scoped SET LOCAL.
SELECT
    name,
    setting,
    unit,
    boot_val                                                     AS engine_default,
    reset_val                                                    AS new_session_value,
    source,
    context,
    short_desc
FROM pg_settings
WHERE name IN (
    'work_mem', 'hash_mem_multiplier', 'maintenance_work_mem',
    'temp_buffers', 'temp_file_limit', 'log_temp_files',
    'max_parallel_workers_per_gather', 'max_parallel_workers',
    'shared_buffers', 'effective_cache_size',
    'enable_sort', 'enable_incremental_sort', 'enable_hashagg'
)
ORDER BY name;

SELECT
    current_setting('work_mem')                                  AS session_work_mem,
    current_setting('hash_mem_multiplier')                        AS session_hash_mem_multiplier,
    current_setting('temp_buffers')                               AS session_temp_buffers,
    current_setting('log_temp_files')                             AS session_log_temp_files,
    current_setting('max_parallel_workers_per_gather')            AS session_parallel_workers;
