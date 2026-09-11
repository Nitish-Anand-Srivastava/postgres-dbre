/*
===============================================================================
SCRIPT NAME:
01_check_tracking_table_status.sql

PURPOSE:
Checks whether dba_toolkit.table_size_history already exists and, if so, reports its row count and capture window.

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
This is optional infrastructure this workflow is responsible for deploying, not a built-in catalog. This script detects its absence via to_regclass() and prints an instructional notice instead of failing when it has not been deployed yet.

EXECUTION ORDER:
Step 01 of workflow 'automation/growth-monitoring'

RELATED SCRIPTS:
02_verify_collection_cadence.sql

HOW TO INTERPRET RESULTS:
A healthy, actively-collecting deployment shows time_since_latest_capture well within one collection interval (for an hourly job, well under an hour; for a daily job, well under a day). A large time_since_latest_capture on an existing table means the collector's schedule has stopped running -- check its pg_cron job status (automation/health-checks) or external scheduler logs, not this table.
===============================================================================
*/

\set tracking_table 'dba_toolkit.table_size_history'
SELECT to_regclass(:'tracking_table') IS NOT NULL AS tracking_table_exists
\gset

\if :tracking_table_exists
SELECT
    count(*)                                     AS total_rows,
    count(DISTINCT (schema_name, table_name))     AS distinct_tables_tracked,
    min(captured_at)                              AS earliest_capture_at,
    max(captured_at)                              AS latest_capture_at,
    now() - max(captured_at)                      AS time_since_latest_capture
FROM dba_toolkit.table_size_history;
\else
SELECT :'tracking_table' || ' does not exist in this database yet. See the deployment runbook in this workflow (script 04) to create it and schedule its periodic collector. Every growth/capacity-forecasting script in this toolkit that depends on it will continue to work today, printing the same notice, until it is deployed.' AS notice;
\endif
