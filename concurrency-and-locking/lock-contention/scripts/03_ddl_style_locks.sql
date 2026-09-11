/*
===============================================================================
SCRIPT NAME:
03_ddl_style_locks.sql

PURPOSE:
Checks specifically for stronger lock modes (ShareUpdateExclusive/ShareRowExclusive/AccessExclusive) contributing to contention.

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
Step 03 of workflow 'concurrency-and-locking/lock-contention'

RELATED SCRIPTS:
../ddl-blocking/README.md

HOW TO INTERPRET RESULTS:
Repeated appearances of these stronger modes during normal operations (not a deliberate maintenance window) suggest an unexpected DDL-like operation (e.g. an ORM auto-migration) is running against production.
===============================================================================
*/

-- Sessions waiting specifically on AccessExclusiveLock / ShareUpdateExclusiveLock
-- style locks typically taken by DDL (CREATE INDEX, ALTER TABLE, VACUUM,
-- TRUNCATE). A queue of these is the classic "DDL blocking the whole app"
-- incident: the DDL itself is waiting on a long-running transaction while
-- every subsequent query queues up behind the DDL's own lock request.
SELECT
    l.pid,
    a.usename,
    a.datname,
    n.nspname                                                   AS schema_name,
    c.relname                                                    AS relation_name,
    l.mode,
    l.granted,
    now() - a.query_start                                        AS wait_duration,
    left(a.query, 200)                                            AS statement
FROM pg_locks l
JOIN pg_stat_activity a ON a.pid = l.pid
LEFT JOIN pg_class c ON c.oid = l.relation
LEFT JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE l.mode IN ('AccessExclusiveLock', 'ShareUpdateExclusiveLock', 'ShareRowExclusiveLock')
ORDER BY l.granted ASC, wait_duration DESC NULLS LAST;
