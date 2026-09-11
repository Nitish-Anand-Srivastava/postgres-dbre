/*
===============================================================================
SCRIPT NAME:
02_reindex_progress_monitor.sql

PURPOSE:
Monitors live progress of any REINDEX CONCURRENTLY (or CREATE INDEX CONCURRENTLY) currently running, to confirm each batch is progressing before starting the next.

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
Step 02 of workflow 'maintenance/reindex-strategy'

RELATED SCRIPTS:
03_reindex_concurrently_runbook.md

HOW TO INTERPRET RESULTS:
A `command` value of 'REINDEX CONCURRENTLY' confirms this is the campaign's own operation; a phase parked on 'waiting for old snapshots' or similar is waiting on another transaction to end, not on I/O -- check concurrency-and-locking/long-running-transactions for what might be holding it up before assuming the rebuild itself is slow.
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
