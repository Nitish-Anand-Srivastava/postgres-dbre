/*
===============================================================================
SCRIPT NAME:
02_memory_and_temp_settings.sql

PURPOSE:
Captures the memory and temp file settings that determine when a sort or hash spills to disk.

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
Step 02 of workflow 'storage-and-capacity/temp-file-growth'

RELATED SCRIPTS:
03_temp_heavy_statements.sql

HOW TO INTERPRET RESULTS:
Read work_mem together with max_connections: the theoretical worst case is roughly work_mem multiplied by the number of concurrent sort/hash nodes across all backends, which is why a value that looks generous per query can be dangerous in aggregate. If log_temp_files is -1 (disabled), enable it with a threshold so future spills are recorded with their query text -- that single change makes every later investigation far easier. The second result set shows existing per-role overrides; a dedicated reporting role with elevated work_mem is the pattern you want, and an inflated override on the trading application's login role is a finding to correct.
===============================================================================
*/

-- The settings that decide whether an operation completes in memory or
-- spills to local disk. On Aurora these come from the DB cluster/instance
-- parameter group rather than postgresql.conf; the `source` column tells
-- you whether the live value came from the parameter group (reported as a
-- configuration file), a session-level SET, a per-role default, or the
-- built-in default.
--
-- The single most important thing to understand here: work_mem is allocated
-- per sort/hash/materialize node, per backend -- NOT per query and not per
-- connection. A plan with four such nodes running across fifty concurrent
-- backends can, worst case, use two hundred times the configured value.
-- That is why raising work_mem globally is risky and why a targeted
-- per-role increase (ALTER ROLE reporting SET work_mem = ...) is almost
-- always the safer remediation.
SELECT
    name,
    setting,
    unit,
    context,
    source,
    short_desc
FROM pg_settings
WHERE name IN (
    'work_mem', 'hash_mem_multiplier', 'maintenance_work_mem',
    'temp_file_limit', 'log_temp_files', 'temp_buffers',
    'max_connections', 'shared_buffers', 'effective_cache_size',
    'enable_sort', 'enable_hashagg', 'random_page_cost'
)
ORDER BY name;

-- Any non-default per-role or per-database overrides already in place.
-- A reporting role with its own elevated work_mem is the recommended
-- pattern; discovering that a *login* role used by the trading application
-- has an inflated override is a finding in its own right.
--
-- Access to pg_db_role_setting is not guaranteed for every role on every
-- deployment, so check SELECT privilege first rather than risking a
-- permission error part-way through the script.
SELECT has_table_privilege(
    current_user, 'pg_catalog.pg_db_role_setting', 'SELECT'
)                                                                 AS can_read_role_settings
\gset

\if :can_read_role_settings
SELECT
    COALESCE(r.rolname, 'ALL ROLES')                              AS role_name,
    COALESCE(d.datname, 'ALL DATABASES')                          AS database_name,
    s.setconfig                                                   AS settings_override
FROM pg_db_role_setting s
LEFT JOIN pg_roles r ON r.oid = s.setrole
LEFT JOIN pg_database d ON d.oid = s.setdatabase
ORDER BY role_name, database_name;
\else
SELECT
    'The current role cannot read pg_catalog.pg_db_role_setting, so existing '
    'per-role/per-database work_mem overrides cannot be listed here. Ask an '
    'administrator to run this part, or inspect a specific role with '
    'the psql meta-command \drds instead.'                        AS notice;
\endif
