/*
===============================================================================
SCRIPT NAME:
03_reconnect_storm_check.sql

PURPOSE:
Checks current connection count/composition for a reconnect storm compounding the cache warm-up effect.

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
Step 03 of workflow 'performance/performance-after-failover'

RELATED SCRIPTS:
../../replication-and-ha/failover-investigation/README.md

HOW TO INTERPRET RESULTS:
A connection count far above the pre-failover baseline, especially many sessions in 'active' state simultaneously attempting reconnection, indicates client-side retry logic is compounding the recovery -- an application-side backoff/jitter fix may be needed in addition to waiting out the cache warm-up.
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
