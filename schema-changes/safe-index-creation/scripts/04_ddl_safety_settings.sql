/*
===============================================================================
SCRIPT NAME:
04_ddl_safety_settings.sql

PURPOSE:
Reads the timeout, memory, and parallelism settings that will govern the build's behavior and its blast radius if it cannot get its lock.

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
Step 04 of workflow 'schema-changes/safe-index-creation'

RELATED SCRIPTS:
05_safe_index_creation_runbook.md

HOW TO INTERPRET RESULTS:
lock_timeout is the setting that matters most. If it is 0 (disabled), a blocking build that cannot acquire its lock will queue indefinitely -- and because a pending lock request blocks every later request on the same table, the whole application queues behind it. Set it at session level before any blocking DDL so the statement fails fast and harmlessly instead. maintenance_work_mem determines whether the build's sort fits in memory; a spill makes the build dramatically slower and consumes per-instance local storage on Aurora. max_parallel_maintenance_workers speeds up a plain CREATE INDEX but does not help a concurrent build in the same way, which is part of why concurrent builds take longer.
===============================================================================
*/

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
