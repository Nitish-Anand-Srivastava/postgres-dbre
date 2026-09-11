/*
===============================================================================
SCRIPT NAME:
03_extension_and_settings_upgrade_surface.sql

PURPOSE:
Inventories installed extensions and the operationally significant settings, so post-upgrade drift and extension updates can be identified against a recorded baseline.

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
Step 03 of workflow 'maintenance/minor-version-upgrade-readiness'

RELATED SCRIPTS:
04_minor_version_upgrade_runbook.md

HOW TO INTERPRET RESULTS:
An engine upgrade moves the available default_version of bundled extensions forward but does not update an already-installed extension in place -- after the upgrade, an extension can remain on its old version until ALTER EXTENSION ... UPDATE is run (see maintenance/extension-upgrade-planning). Record the installed versions here so that post-upgrade comparison is a lookup rather than a guess. The key-settings snapshot serves the same purpose for configuration: an upgrade that also moves the cluster to a new default parameter group family can silently change a default, and this baseline is what makes that visible.
===============================================================================
*/

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

-- Confirms whether a specific extension is available to install on this
-- Aurora PostgreSQL instance (it may be available but not yet CREATE
-- EXTENSION'd). Aurora PostgreSQL supports a curated allowlist of
-- extensions per engine version; if an extension you need is missing from
-- pg_available_extensions entirely (not just pg_extension), it is not
-- supported on this Aurora engine version and must be requested via AWS
-- support or worked around at the application layer.
\set extension_name 'pg_stat_statements'
SELECT
    name,
    default_version,
    installed_version,
    comment
FROM pg_available_extensions
WHERE name = :'extension_name';

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
