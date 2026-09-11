/*
===============================================================================
SCRIPT NAME:
03_statistics_targets.sql

PURPOSE:
Shows the per-column statistics target for one table alongside the cluster default.

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
Step 03 of workflow 'query-optimization/cardinality-estimation'

RELATED SCRIPTS:
04_extended_statistics_inventory.sql

HOW TO INTERPRET RESULTS:
The default target of 100 stores at most 100 most-common values and 100 histogram buckets per column. That is ample for a boolean or a small enumeration and wholly inadequate for a heavily skewed, high-cardinality column such as market symbol on an exchange with hundreds of listed pairs. Where script 02 showed mcv_entries pinned at the target and a long tail of values below it, raising that column's target (commonly to 500 or 1000) and re-analyzing is the direct fix. Raise it per column, not cluster-wide: a higher default makes every ANALYZE slower and every planning cycle more expensive.
===============================================================================
*/

-- How much resolution the planner is allowed to keep for each column.
-- The statistics target controls both the number of most-common-value
-- entries and the number of histogram buckets stored by ANALYZE.
--
-- PostgreSQL 17 note: pg_attribute.attstattarget is nullable, and NULL
-- means "use default_statistics_target" (earlier versions stored -1 for
-- the same meaning). It is coalesced to -1 below so the two conventions
-- read identically.
--
-- The relation name is only compared inside a WHERE clause, so a name that
-- does not exist yields zero rows rather than an error.
\set schema_name 'public'
\set table_name 'orders'
SELECT
    n.nspname                                                    AS schema_name,
    c.relname                                                    AS table_name,
    a.attname                                                    AS column_name,
    a.attnum                                                     AS column_position,
    format_type(a.atttypid, a.atttypmod)                          AS column_type,
    coalesce(a.attstattarget, -1)                                 AS column_statistics_target,
    (SELECT setting::int FROM pg_settings WHERE name = 'default_statistics_target')
                                                                  AS default_statistics_target,
    CASE
        WHEN coalesce(a.attstattarget, -1) < 0
            THEN 'inherits default_statistics_target'
        ELSE 'explicit per-column override'
    END                                                           AS target_source,
    a.attnotnull                                                  AS is_not_null
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = :'schema_name'
  AND c.relname = :'table_name'
  AND a.attnum > 0
  AND NOT a.attisdropped
ORDER BY a.attnum;
