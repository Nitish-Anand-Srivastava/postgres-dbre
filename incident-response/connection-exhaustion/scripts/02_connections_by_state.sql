/*
===============================================================================
SCRIPT NAME:
02_connections_by_state.sql

PURPOSE:
Breaks the connections down by state, which determines both who owns them and how safely they can be reclaimed.

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
Step 02 of workflow 'incident-response/connection-exhaustion'

RELATED SCRIPTS:
03_connections_by_application.sql

HOW TO INTERPRET RESULTS:
Idle means a pool is hoarding slots (cheap to reclaim). Idle in transaction means an application bug holding snapshots and locks (valuable to reclaim, but with rollback consequences). Active means the database is slow and each request is holding its slot longer -- in that case stop reclaiming and fix the slowness.
===============================================================================
*/

-- Connection counts by database and state, compared against max_connections
-- so the operator can see headroom immediately.
SELECT
    coalesce(datname, '(no database / background worker)')     AS datname,
    state,
    count(*)                                                    AS session_count,
    round(
        100.0 * count(*) / NULLIF((SELECT setting::numeric FROM pg_settings WHERE name = 'max_connections'), 0),
        2
    )                                                            AS pct_of_max_connections
FROM pg_stat_activity
GROUP BY datname, state
ORDER BY session_count DESC;
