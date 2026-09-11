/*
===============================================================================
SCRIPT NAME:
02_current_isolation_levels.sql

PURPOSE:
Shows the transaction isolation level in use by each currently active session.

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
Step 02 of workflow 'concurrency-and-locking/transaction-contention'

RELATED SCRIPTS:
03_contended_rows.sql

HOW TO INTERPRET RESULTS:
This shows the session/database default, not necessarily what a specific transaction explicitly requested via `SET TRANSACTION ISOLATION LEVEL`; combine with an application-code review to confirm the actual isolation level used for the contended pattern.
===============================================================================
*/

-- Current transaction isolation level per active backend. Non-default
-- levels (repeatable read, serializable) are far more prone to serialization
-- failures under concurrent hot-row access than read committed.
SELECT
    a.pid,
    a.usename,
    a.application_name,
    s.setting                                                   AS session_default_isolation,
    a.state,
    left(a.query, 160)                                           AS current_query
FROM pg_stat_activity a
CROSS JOIN LATERAL (
    SELECT setting FROM pg_settings WHERE name = 'transaction_isolation'
) s
WHERE a.pid <> pg_backend_pid()
  AND a.state <> 'idle'
ORDER BY a.application_name;
