/*
===============================================================================
SCRIPT NAME:
04_memory_and_logging_settings.sql

PURPOSE:
Reviews the memory budget, the temp file limit, and whether spills are being logged.

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
Step 04 of workflow 'query-optimization/temp-file-investigation'

RELATED SCRIPTS:
05_correlate_and_reproduce_safely.md

HOW TO INTERPRET RESULTS:
Three findings matter here. log_temp_files at -1 means no spill is ever logged, so attribution depends entirely on cumulative counters -- set it to 0 in the Aurora cluster parameter group for full visibility at negligible cost. temp_file_limit at -1 means a single runaway query can consume all local storage; a bounded value makes it fail instead, which is usually the better outcome for an analytical role. And work_mem must be read as a per-node, per-worker budget, so the instance-level exposure is much larger than the configured value suggests.
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
