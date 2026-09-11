/*
===============================================================================
SCRIPT NAME:
01_service_connection_detail.sql

PURPOSE:
Detailed connection/state/query breakdown filtered to a specific application, for deep-dive analysis.

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
Step 01 of workflow 'connections/application-connection-analysis'

RELATED SCRIPTS:
../connection-pooling/README.md

HOW TO INTERPRET RESULTS:
A wide spread of connection_age values with many very-old connections suggests long-lived pooled connections (expected for a healthy pool); many very-young, rapidly cycling connections suggest the service is not pooling at all and opening a new connection per request.
===============================================================================
*/

-- Detailed per-session view for a specific application, to characterize its
-- exact connection and query behavior for a targeted investigation. This
-- is a WHERE-clause filter (not a relation reference), so an unmatched
-- default application name simply returns zero rows -- edit the \set line
-- below to the real application_name under investigation.
\set target_application_name 'order-service'
SELECT
    pid,
    usename,
    client_addr,
    state,
    backend_start,
    now() - backend_start                                        AS connection_age,
    now() - state_change                                          AS time_in_current_state,
    left(query, 160)                                              AS current_or_last_query
FROM pg_stat_activity
WHERE application_name = :'target_application_name'
ORDER BY connection_age DESC;
