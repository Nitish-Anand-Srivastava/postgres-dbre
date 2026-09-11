/*
===============================================================================
SCRIPT NAME:
01_effective_timeout_settings.sql

PURPOSE:
Reads the timeout and concurrency settings this connection actually resolved to.

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
Step 01 of workflow 'incident-response/application-timeouts'

RELATED SCRIPTS:
02_role_and_database_overrides.sql

HOW TO INTERPRET RESULTS:
Check statement_timeout, lock_timeout and idle_in_transaction_session_timeout. A statement_timeout of 0 means the server is not cancelling anything, so any timeout the application reports is client-side however its error message is worded. Remember these are YOUR session's values; script 02 shows what other roles get.
===============================================================================
*/

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
