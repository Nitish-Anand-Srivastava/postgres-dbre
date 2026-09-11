/*
===============================================================================
SCRIPT NAME:
03_autoanalyze_configuration.sql

PURPOSE:
Shows the global autoanalyze settings and any per-table overrides that change or disable them.

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
Step 03 of workflow 'query-optimization/stale-statistics'

RELATED SCRIPTS:
04_stored_statistics_for_table.sql

HOW TO INTERPRET RESULTS:
autovacuum_analyze_scale_factor is a fraction of the table, so the absolute trigger point is threshold plus scale_factor multiplied by row count. At the default 0.1, a 500 million row trades table needs 50 million modifications before autoanalyze fires -- far too coarse for a table whose distribution shifts during every volatility event. The fix is a per-table override such as autovacuum_analyze_scale_factor = 0.01 on the largest tables. In the second result set, any table carrying autovacuum_enabled=false should be justified in writing or reverted.
===============================================================================
*/

-- Global autovacuum/autoanalyze configuration. On Aurora these come from
-- the DB cluster parameter group rather than postgresql.conf.
SELECT
    name,
    setting,
    unit,
    boot_val                                                     AS engine_default,
    reset_val                                                    AS new_session_value,
    source,
    short_desc
FROM pg_settings
WHERE name IN (
    'autovacuum',
    'autovacuum_analyze_threshold',
    'autovacuum_analyze_scale_factor',
    'autovacuum_vacuum_threshold',
    'autovacuum_vacuum_scale_factor',
    'autovacuum_vacuum_insert_threshold',
    'autovacuum_vacuum_insert_scale_factor',
    'autovacuum_max_workers',
    'autovacuum_naptime',
    'default_statistics_target'
)
ORDER BY name;

-- Per-table storage options. A reloptions entry containing
-- autovacuum_enabled=false disables autoANALYZE for that table as well as
-- autovacuum, which is a very common reason a single table's statistics
-- are indefinitely stale while every other table is fine.
SELECT
    n.nspname                                                    AS schema_name,
    c.relname                                                    AS table_name,
    c.relkind,
    pg_size_pretty(pg_total_relation_size(c.oid))                 AS total_size,
    c.reloptions                                                  AS per_table_options
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p', 'm')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND c.reloptions IS NOT NULL
ORDER BY pg_total_relation_size(c.oid) DESC;
