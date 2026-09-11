/*
===============================================================================
SCRIPT NAME:
03_largest_objects_and_growth_trend.sql

PURPOSE:
Largest-object snapshot plus, where the growth-monitoring collector is deployed, the actual per-table growth rate over the retention window -- the two halves of a capacity trend.

AURORA POSTGRESQL VERSION:
Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise)

EXECUTION LOCATION:
Writer instance preferred; safe to run on a reader but results reflect only that reader's local activity

SAFETY:
READ ONLY

EXPECTED IMPACT:
Minimal -- reads system catalogs/statistics views only, no table locks beyond a brief catalog lookup.

REQUIRED PRIVILEGES:
Role membership in `pg_monitor` (or `pg_read_all_stats`) is sufficient. No superuser required.

PREREQUISITES:
None beyond CONNECT on the target database.

EXECUTION ORDER:
Step 03 of workflow 'automation/capacity-monitoring'

RELATED SCRIPTS:
04_scheduling_runbook.md, ../growth-monitoring/README.md, ../../tables-and-indexes/large-tables/README.md

HOW TO INTERPRET RESULTS:
The first result is a point-in-time ranking: which objects dominate the volume today. The second is the part that actually supports a forecast, and it only returns rows once automation/growth-monitoring's dba_toolkit.table_size_history collector has been running for at least two collection intervals -- until then it prints an instructional notice, which is the expected state, not an error. Alert on growth rate, not absolute size: a trade-fills, order-events, or audit-ledger table adding a predictable amount per day tells you when the current storage and instance sizing runs out, which is the number a capacity review actually needs. Hand the fastest growers to archival-and-data-lifecycle/archive-large-table or a partitioning plan well before the ceiling.
===============================================================================
*/

-- Largest tables in the current database by total size (heap + indexes +
-- TOAST), which is what actually matters for storage capacity planning and
-- I/O footprint.
\set top_n 30
SELECT
    n.nspname                                                   AS schema_name,
    c.relname                                                   AS table_name,
    pg_size_pretty(pg_relation_size(c.oid))                       AS heap_size,
    pg_size_pretty(pg_indexes_size(c.oid))                        AS index_size,
    pg_size_pretty(pg_total_relation_size(c.oid))                 AS total_size,
    c.reltuples::bigint                                          AS estimated_row_count
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY pg_total_relation_size(c.oid) DESC
LIMIT :top_n;

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
