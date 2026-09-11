/*
===============================================================================
SCRIPT NAME:
01_current_activity_snapshot.sql

PURPOSE:
One-shot snapshot of all backends grouped by state and wait event, to see whether anything is abnormal right now.

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
Step 01 of workflow 'database-health/daily-health-check'

RELATED SCRIPTS:
02_connection_headroom.sql

HOW TO INTERPRET RESULTS:
Read this as a shape, not a number: a healthy exchange writer shows mostly short active queries plus pooled idle connections. A large Lock wait_event_type group, or a longest_txn_runtime measured in minutes, means stop the daily sweep and investigate that first.
===============================================================================
*/

-- Snapshot of every backend known to this instance right now, grouped by
-- high-level state. Run this first on any performance or availability
-- investigation to understand overall load before drilling into detail.
SELECT
    datname,
    state,
    wait_event_type,
    count(*)                                                   AS session_count,
    count(*) FILTER (WHERE state = 'active')                   AS active_count,
    max(now() - query_start)                                   AS longest_query_runtime,
    max(now() - xact_start)                                    AS longest_txn_runtime
FROM pg_stat_activity
WHERE pid <> pg_backend_pid()
GROUP BY datname, state, wait_event_type
ORDER BY session_count DESC, longest_query_runtime DESC NULLS LAST;
