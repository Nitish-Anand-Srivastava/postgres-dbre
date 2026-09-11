/*
===============================================================================
SCRIPT NAME:
04_monitor_build_progress.sql

PURPOSE:
Monitors an in-flight index build, showing its phase, progress, and the backend it is waiting on.

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
Step 04 of workflow 'schema-changes/concurrent-index-build'

RELATED SCRIPTS:
05_blocking_sessions_during_build.sql

HOW TO INTERPRET RESULTS:
Read the phase column, not the percentages. 'building index' or 'index validation: scanning index' means real work is happening and the numbers will move. 'waiting for writers before validation' or 'waiting for readers before marking dead' means the build is doing nothing and is waiting for older transactions to end -- progress will not resume until they do, no matter how long you wait. When the build is in a waiting phase, current_locker_pid names the exact backend responsible, and that backend is your whole problem. Remember there are two full passes, so reaching the end of blocks_done once means roughly halfway. Run this from a second session every minute or two rather than once; the phase transitions are what tell you the build is healthy.
===============================================================================
*/

-- Live progress of any index build currently running on this instance,
-- read from pg_stat_progress_create_index. This covers both the blocking
-- and the non-blocking build forms as well as reindex operations; the
-- `command` column tells you which one is running.
--
-- The `phase` column is the key field: a build that is parked in
-- "waiting for writers before validation" or "waiting for readers before
-- marking dead" is not slow because of I/O -- it is waiting for older
-- transactions to finish, and no amount of waiting will help until those
-- transactions commit or are ended. `current_locker_pid` names the exact
-- backend being waited on.
SELECT
    p.pid,
    p.datname,
    n.nspname                                                    AS schema_name,
    c.relname                                                    AS table_name,
    i.relname                                                    AS index_name,
    p.command,
    p.phase,
    p.lockers_total,
    p.lockers_done,
    p.current_locker_pid,
    p.blocks_done,
    p.blocks_total,
    round(100.0 * p.blocks_done / NULLIF(p.blocks_total, 0), 1)   AS pct_blocks_done,
    p.tuples_done,
    p.tuples_total,
    round(100.0 * p.tuples_done / NULLIF(p.tuples_total, 0), 1)   AS pct_tuples_done,
    p.partitions_done,
    p.partitions_total,
    now() - a.query_start                                        AS elapsed,
    left(a.query, 200)                                           AS statement
FROM pg_stat_progress_create_index p
LEFT JOIN pg_class c ON c.oid = p.relid
LEFT JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_class i ON i.oid = p.index_relid
LEFT JOIN pg_stat_activity a ON a.pid = p.pid
ORDER BY elapsed DESC NULLS LAST;
