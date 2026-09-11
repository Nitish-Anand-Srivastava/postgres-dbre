/*
===============================================================================
SCRIPT NAME:
01_connection_headroom.sql

PURPOSE:
Measures how close the instance is to its connection ceiling, including the reserved superuser slots.

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
Step 01 of workflow 'incident-response/connection-exhaustion'

RELATED SCRIPTS:
02_connections_by_state.sql

HOW TO INTERPRET RESULTS:
pct_utilized at or above roughly 95% confirms exhaustion: with superuser_reserved_connections subtracted, application roles are already being refused. Record this number before and after every reclaim action so you can prove whether it is working.
===============================================================================
*/

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
