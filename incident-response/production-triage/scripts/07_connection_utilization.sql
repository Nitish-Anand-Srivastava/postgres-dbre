/*
===============================================================================
SCRIPT NAME:
07_connection_utilization.sql

PURPOSE:
Step 7 of 10: connection counts by state and current utilization against the connection ceiling.

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
Step 07 of workflow 'incident-response/production-triage'

RELATED SCRIPTS:
08_top_queries.sql, ../connection-exhaustion/README.md

HOW TO INTERPRET RESULTS:
This tells you how much time you have. Utilization near the ceiling means the incident is about to become an availability incident regardless of its original cause, which raises the priority of everything else you have found. A state mix dominated by idle means a pool is hoarding slots; dominated by active means the database is slow and each request is holding its slot longer.
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

-- Current connection utilization vs. the effective connection ceiling.
-- On Aurora, max_connections is derived from the instance class's memory
-- (via the parameter group formula) rather than freely set, so headroom
-- must be planned around instance class, not just the GUC value alone.
SELECT
    (SELECT setting::int FROM pg_settings WHERE name = 'max_connections')      AS max_connections,
    (SELECT setting::int FROM pg_settings WHERE name = 'superuser_reserved_connections') AS superuser_reserved,
    (SELECT count(*) FROM pg_stat_activity)                                    AS current_total_connections,
    (SELECT count(*) FROM pg_stat_activity WHERE state = 'active')             AS current_active_connections,
    round(
        100.0 * (SELECT count(*) FROM pg_stat_activity) /
        NULLIF((SELECT setting::numeric FROM pg_settings WHERE name = 'max_connections'), 0),
        2
    )                                                                          AS pct_utilized;
