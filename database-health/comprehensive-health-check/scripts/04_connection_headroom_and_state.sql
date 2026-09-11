/*
===============================================================================
SCRIPT NAME:
04_connection_headroom_and_state.sql

PURPOSE:
Measures connection utilization against max_connections and breaks current sessions down by database and state.

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
Step 04 of workflow 'database-health/comprehensive-health-check'

RELATED SCRIPTS:
05_open_transaction_horizon.sql, ../../connections/connection-exhaustion/README.md

HOW TO INTERPRET RESULTS:
pct_utilized above 85% is the point at which a volatility-driven traffic burst can exhaust connections and lock out the matching engine and withdrawal workers. A large idle count relative to active is normal for a pooled application; a large 'idle in transaction' count is never normal and is investigated in script 05. Remember that max_connections on Aurora is derived from the instance class via the parameter-group formula, so headroom is fixed by instance sizing, not freely tunable.
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
