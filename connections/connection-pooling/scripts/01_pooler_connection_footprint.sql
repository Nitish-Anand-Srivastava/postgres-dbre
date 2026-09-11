/*
===============================================================================
SCRIPT NAME:
01_pooler_connection_footprint.sql

PURPOSE:
Checks how many database-side connections the pooler's application_name/user is actually consuming, to distinguish a database-side vs. pooler-side bottleneck.

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
Step 01 of workflow 'connections/connection-pooling'

RELATED SCRIPTS:
../connection-exhaustion/README.md

HOW TO INTERPRET RESULTS:
A small, stable connection count here despite application-visible connection errors strongly suggests the bottleneck is on the pooler side (or between application and pooler) -- pivot to the pooler's own admin console (SHOW POOLS) rather than continuing PostgreSQL-side investigation.
===============================================================================
*/

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
