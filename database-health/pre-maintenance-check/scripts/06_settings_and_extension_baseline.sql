/*
===============================================================================
SCRIPT NAME:
06_settings_and_extension_baseline.sql

PURPOSE:
Captures the current configuration settings and installed extension inventory as a pre-maintenance baseline.

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
Step 06 of workflow 'database-health/pre-maintenance-check'

RELATED SCRIPTS:
07_query_performance_baseline.sql

HOW TO INTERPRET RESULTS:
Save this output with the maintenance ticket. It is the reference point post-maintenance-check uses to confirm a parameter-group change took effect as intended, or that a major-version/extension upgrade did not silently change a setting's effective value or an extension's version.
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

-- Extensions currently installed in this database vs. what Aurora
-- PostgreSQL makes available. Many investigation scripts in this toolkit
-- depend on pg_stat_statements (query stats) and/or pgstattuple (exact
-- bloat); confirm both are available/installed before relying on those
-- scripts.
SELECT
    e.extname,
    e.extversion,
    n.nspname                                                   AS installed_schema
FROM pg_extension e
JOIN pg_namespace n ON n.oid = e.extnamespace
ORDER BY e.extname;
