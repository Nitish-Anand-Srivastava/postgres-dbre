/*
===============================================================================
SCRIPT NAME:
01_ddl_lock_waits.sql

PURPOSE:
Shows sessions holding or waiting on the strong lock modes taken by DDL, which immediately reveals whether a schema change is at the head of the problem.

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
Step 01 of workflow 'schema-changes/ddl-lock-investigation'

RELATED SCRIPTS:
02_blocked_sessions_overview.sql

HOW TO INTERPRET RESULTS:
This is the first script to run and frequently the only one you need. Rows are ordered with ungranted requests first: if you see an ALTER TABLE, CREATE INDEX, or DROP INDEX with granted = false and a long wait_duration, you have found the head of the queue. That statement has done no work at all, yet its pending AccessExclusiveLock request is blocking every later query on the relation -- including plain SELECTs that would never have conflicted with the current holders. Cancelling it is normally the fastest route back to service, and the queue drains within seconds. Note the relation_name, because it tells you exactly which part of the application is affected.
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
