/*
===============================================================================
SCRIPT NAME:
03_connections_by_application.sql

PURPOSE:
Attributes the connections to a service and user so the owning team can be contacted while reclaim is still in progress.

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
Step 03 of workflow 'incident-response/connection-exhaustion'

RELATED SCRIPTS:
04_long_idle_sessions.sql

HOW TO INTERPRET RESULTS:
One application_name holding a disproportionate share names the owning team immediately. A large '(unset)' group means those services do not set application_name, which is a follow-up action worth insisting on -- attribution is what makes this incident solvable in minutes rather than hours.
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
