/*
===============================================================================
SCRIPT NAME:
02_table_growth_trend.sql

PURPOSE:
Computes table growth over time from an optional periodic size-history tracking table, if one has been deployed.

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
Step 02 of workflow 'database-health/capacity-health-check'

RELATED SCRIPTS:
03_connection_capacity_headroom.sql, ../../storage-and-capacity/table-growth/README.md

HOW TO INTERPRET RESULTS:
If the tracking table does not exist yet, this prints an instructional notice rather than failing -- deploy the collector in automation/growth-monitoring and treat today's script 01 output as the first snapshot. If it does exist, the growth-over-window figures for the largest tables are the actual number that drives 'how many months until this table is a problem', not the single-point-in-time size alone.
===============================================================================
*/

-- Table size growth over time requires two or more point-in-time samples.
-- This query assumes you are periodically appending
-- (now(), schemaname, relname, pg_total_relation_size(relid)) rows into a
-- tracking table (see automation/growth-monitoring/ for a ready-to-schedule
-- collector that creates and populates it) and computes growth between the
-- earliest and latest sample in the retention window.
--
-- This tracking table is optional infrastructure, not a built-in catalog --
-- on a database where the collector has never been deployed, the table
-- will not exist yet. to_regclass() is used (rather than a bare
-- `FROM dba_toolkit.table_size_history`, or a `::regclass` cast, both of
-- which fail at parse/analysis time with "relation does not exist" the
-- moment the statement is sent) so this script can detect that case and
-- print an instructional notice instead of hard-failing.
\set tracking_table 'dba_toolkit.table_size_history'
\set lookback_days 30
SELECT to_regclass(:'tracking_table') IS NOT NULL                AS tracking_table_exists
\gset

\if :tracking_table_exists
SELECT
    schema_name,
    table_name,
    min(size_bytes)  FILTER (WHERE captured_at = first_capture) AS start_size_bytes,
    max(size_bytes)  FILTER (WHERE captured_at = last_capture)  AS end_size_bytes,
    pg_size_pretty(
        (max(size_bytes) FILTER (WHERE captured_at = last_capture) -
         min(size_bytes) FILTER (WHERE captured_at = first_capture))::bigint
    )                                                            AS growth_over_window
FROM (
    SELECT
        schema_name,
        table_name,
        captured_at,
        size_bytes,
        min(captured_at) OVER (PARTITION BY schema_name, table_name) AS first_capture,
        max(captured_at) OVER (PARTITION BY schema_name, table_name) AS last_capture
    FROM dba_toolkit.table_size_history
    WHERE captured_at > now() - make_interval(days => :lookback_days)
) sized
GROUP BY schema_name, table_name
ORDER BY (max(size_bytes) - min(size_bytes)) DESC;
\else
SELECT
    :'tracking_table' || ' does not exist in this database, so no growth-'
    'over-time history is available yet. Deploy the collector in '
    'automation/growth-monitoring/ (it creates this table and schedules a '
    'periodic INSERT of current relation sizes) and re-run this script '
    'after at least two collection intervals have elapsed. In the '
    'meantime, use storage-and-capacity/table-growth for a single-point-in-'
    'time size snapshot.'                                        AS notice;
\endif
