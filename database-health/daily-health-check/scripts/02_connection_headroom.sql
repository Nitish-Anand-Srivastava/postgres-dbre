/*
===============================================================================
SCRIPT NAME:
02_connection_headroom.sql

PURPOSE:
Connection utilization against max_connections, plus a breakdown by application and user.

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
Step 02 of workflow 'database-health/daily-health-check'

RELATED SCRIPTS:
03_transaction_and_idle_check.sql, ../../connections/application-connection-analysis/README.md

HOW TO INTERPRET RESULTS:
The per-application breakdown localizes a rising trend to a specific service (matching engine, wallet service, market-data API, reporting) instead of leaving it as an unattributed cluster-level number. A service whose count grew overnight without a deployment is usually leaking connections or has had its pool size changed by an autoscaling event.
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

-- Connection counts broken down by application_name and usename. Useful to
-- identify which service, connection pool, or batch job is responsible for
-- a spike or leak in connection count.
SELECT
    coalesce(NULLIF(application_name, ''), '(unset)')           AS application_name,
    usename,
    datname,
    count(*)                                                    AS session_count,
    count(*) FILTER (WHERE state = 'active')                    AS active_count,
    count(*) FILTER (WHERE state = 'idle')                      AS idle_count,
    count(*) FILTER (WHERE state = 'idle in transaction')       AS idle_in_txn_count
FROM pg_stat_activity
WHERE pid <> pg_backend_pid()
GROUP BY application_name, usename, datname
ORDER BY session_count DESC;
