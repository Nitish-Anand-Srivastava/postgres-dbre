/*
===============================================================================
SCRIPT NAME:
04_connection_pool_headroom.sql

PURPOSE:
Checks whether the connection pool itself is capping achievable concurrency/throughput.

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
Step 04 of workflow 'performance/throughput-degradation'

RELATED SCRIPTS:
05_replication_slot_backpressure.sql

HOW TO INTERPRET RESULTS:
If utilization is near 100% and the workload is designed to run many concurrent transactions, the pool ceiling -- not the database engine -- may be the throughput limiter.
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
