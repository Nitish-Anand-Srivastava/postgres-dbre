/*
===============================================================================
SCRIPT NAME:
03_column_targets_and_extended_statistics.sql

PURPOSE:
Lists non-default per-column statistics targets and every extended (multi-column) statistics object, so correlated-column tuning is visible and not duplicated.

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
Step 03 of workflow 'maintenance/statistics-maintenance'

RELATED SCRIPTS:
04_statistics_maintenance_runbook.md

HOW TO INTERPRET RESULTS:
An empty first result means every column is using the cluster default target, which is the normal starting state -- it is a finding only for tables whose plans are known to be wrong on a skewed column (a symbol or market column where a few pairs carry most of the volume). An empty second result means the planner is assuming every column is statistically independent everywhere, which is where correlated-predicate underestimates come from. A visibility_status warning means either ANALYZE has not populated the object or the current role lacks SELECT privilege on the underlying table; verify privileges before concluding the object is stale. Do not create extended statistics speculatively across every column pair -- each one adds ANALYZE cost, so add them for the specific correlated predicates that appear in real slow plans.
===============================================================================
*/

-- Columns with a non-default statistics target. In PostgreSQL 17
-- attstattarget is NULL when the column simply inherits the
-- default_statistics_target GUC (older releases stored -1 for the same
-- meaning), so filtering on attstattarget >= 0 returns only deliberate
-- (or long-forgotten) per-column overrides under either convention.
SELECT
    n.nspname                                                    AS schema_name,
    c.relname                                                    AS table_name,
    a.attname                                                    AS column_name,
    a.attstattarget                                              AS column_statistics_target,
    (SELECT setting::int FROM pg_settings WHERE name = 'default_statistics_target')
                                                                 AS cluster_default_target
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE a.attnum > 0
  AND NOT a.attisdropped
  AND a.attstattarget >= 0
  AND c.relkind IN ('r', 'p', 'm')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY a.attstattarget DESC, n.nspname, c.relname, a.attname;

-- Extended statistics objects: these are how the planner learns that two
-- columns are correlated (ndistinct / dependencies) or how often specific
-- value combinations occur (mcv). Use the permission-filtered pg_stats_ext
-- view for populated data rather than pg_statistic_ext_data, which is
-- restricted to elevated roles on Aurora PostgreSQL. A NULL data column can
-- therefore mean either that ANALYZE has not populated the object yet or that
-- the current role cannot inspect the underlying table.
SELECT
    sn.nspname                                                   AS statistics_schema,
    s.stxname                                                    AS statistics_name,
    tn.nspname                                                   AS table_schema,
    t.relname                                                    AS table_name,
    s.stxkind                                                    AS kinds,
    (e.n_distinct IS NOT NULL)                                   AS ndistinct_visible,
    (e.dependencies IS NOT NULL)                                 AS dependencies_visible,
    (e.most_common_vals IS NOT NULL)                             AS mcv_visible,
    CASE
        WHEN e.statistics_name IS NULL THEN
            'statistics data not populated or not visible to current role'
        ELSE 'statistics data visible'
    END                                                          AS visibility_status
FROM pg_statistic_ext s
JOIN pg_class t ON t.oid = s.stxrelid
JOIN pg_namespace tn ON tn.oid = t.relnamespace
JOIN pg_namespace sn ON sn.oid = s.stxnamespace
LEFT JOIN pg_stats_ext e
       ON e.statistics_schemaname = sn.nspname
      AND e.statistics_name = s.stxname
ORDER BY tn.nspname, t.relname, s.stxname;
