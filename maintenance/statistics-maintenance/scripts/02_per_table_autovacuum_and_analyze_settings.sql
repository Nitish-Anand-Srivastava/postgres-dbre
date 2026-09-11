/*
===============================================================================
SCRIPT NAME:
02_per_table_autovacuum_and_analyze_settings.sql

PURPOSE:
Shows which tables already carry per-table autovacuum/analyze storage parameter overrides, alongside their current size and churn, so tuning decisions build on what is already configured.

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
Step 02 of workflow 'maintenance/statistics-maintenance'

RELATED SCRIPTS:
03_column_targets_and_extended_statistics.sql

HOW TO INTERPRET RESULTS:
Read this as size-ranked rather than problem-ranked: the question for each of the largest tables is whether per_table_overrides is NULL when it should not be. A 500 million row trades table inheriting the default analyze scale factor of 0.1 needs 50 million modified rows before autoanalyze fires, which is almost never the behavior you want on a time-series-skewed table. Conversely, an override present on a now-small table (a partition that has aged out, a table that was archived down) is stale configuration worth removing so autovacuum workers are not woken up for no reason.
===============================================================================
*/

-- Per-table storage parameter overrides (reloptions) alongside size and
-- churn. A table with no reloptions simply inherits the cluster-wide
-- autovacuum/autoanalyze settings from the DB cluster parameter group.
-- reloptions is a text[] of 'key=value' entries; it is displayed as-is
-- rather than parsed, so an unexpected or obsolete override is visible
-- exactly as it was set.
\set top_n 50
SELECT
    n.nspname                                                    AS schema_name,
    c.relname                                                    AS table_name,
    pg_size_pretty(pg_total_relation_size(c.oid))                AS total_size,
    c.reltuples::bigint                                          AS estimated_rows,
    c.reloptions                                                 AS per_table_overrides,
    s.n_live_tup,
    s.n_mod_since_analyze,
    round(
        100.0 * s.n_mod_since_analyze / NULLIF(s.n_live_tup, 0), 2
    )                                                            AS pct_modified_since_analyze,
    s.last_analyze,
    s.last_autoanalyze
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_stat_all_tables s ON s.relid = c.oid
WHERE c.relkind IN ('r', 'p', 'm')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY pg_total_relation_size(c.oid) DESC
LIMIT :top_n;
