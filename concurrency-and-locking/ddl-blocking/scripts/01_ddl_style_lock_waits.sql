/*
===============================================================================
SCRIPT NAME:
01_ddl_style_lock_waits.sql

PURPOSE:
Identifies sessions holding or waiting for strong (DDL-style) lock modes and whether the DDL itself is granted or queued.

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
Step 01 of workflow 'concurrency-and-locking/ddl-blocking'

RELATED SCRIPTS:
02_who_is_queued_behind_ddl.sql

HOW TO INTERPRET RESULTS:
A DDL statement with granted = false means it is the one waiting, not the one blocking -- everyone else is queued behind IT, waiting for its lock request to clear the queue ahead of them.
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
