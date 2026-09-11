/*
===============================================================================
SCRIPT NAME:
02_verify_collection_cadence.sql

PURPOSE:
Where the tracking table exists, checks for gaps between consecutive capture timestamps to confirm the collector is running on a healthy, consistent cadence.

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
Step 02 of workflow 'automation/growth-monitoring'

RELATED SCRIPTS:
03_deploy_collector_runbook.md

HOW TO INTERPRET RESULTS:
This lists the largest gaps between consecutive collection runs over the lookback window, largest first. A consistent cadence shows every gap close to the intended collection interval (e.g. 1 hour). A gap much larger than the intended interval means the collector missed one or more scheduled runs during that window -- correlate the timing against the pg_cron job run history (automation/health-checks) or the external scheduler's own logs to find why.
===============================================================================
*/

\set tracking_table 'dba_toolkit.table_size_history'
SELECT to_regclass(:'tracking_table') IS NOT NULL AS tracking_table_exists
\gset

\if :tracking_table_exists
\set lookback_days 30
WITH captures AS (
    SELECT DISTINCT captured_at
    FROM dba_toolkit.table_size_history
    WHERE captured_at > now() - make_interval(days => :lookback_days)
),
gaps AS (
    SELECT
        captured_at,
        lag(captured_at) OVER (ORDER BY captured_at)                       AS previous_capture_at,
        captured_at - lag(captured_at) OVER (ORDER BY captured_at)          AS gap_since_previous
    FROM captures
)
SELECT
    previous_capture_at,
    captured_at,
    gap_since_previous
FROM gaps
WHERE gap_since_previous IS NOT NULL
ORDER BY gap_since_previous DESC
LIMIT 20;
\else
SELECT :'tracking_table' || ' does not exist in this database yet, so no collection cadence can be verified. See the deployment runbook in this workflow (script 03).' AS notice;
\endif
