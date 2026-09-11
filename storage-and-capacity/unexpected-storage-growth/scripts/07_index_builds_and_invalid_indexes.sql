/*
===============================================================================
SCRIPT NAME:
07_index_builds_and_invalid_indexes.sql

PURPOSE:
Finds in-progress index builds consuming space right now, and INVALID indexes left behind by builds that already failed.

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
Step 07 of workflow 'storage-and-capacity/unexpected-storage-growth'

RELATED SCRIPTS:
../../schema-changes/failed-index-build/README.md

HOW TO INTERPRET RESULTS:
An in-progress build in the first result set explains a live, transient step up in storage: the new index is being written alongside the existing data, and on a very large exchange table that can be a substantial amount of space. That is expected and will complete -- but on Aurora the volume high-water mark it creates is permanent, so record it rather than dismissing it. The second result set is the aftermath case: INVALID indexes from builds that were cancelled, timed out, or died with their session. Those consume their full size while being completely unusable by the planner, and they are the one thing in this entire workflow you can drop with no query-plan risk whatsoever.
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

-- Indexes left in an INVALID state, almost always because a previous
-- CREATE INDEX CONCURRENTLY or REINDEX CONCURRENTLY failed partway through
-- (a killed session, statement_timeout, or deadlock). Invalid indexes are
-- not used by the planner but still consume storage and slow down writes,
-- so they should be dropped and, if needed, recreated concurrently.
SELECT
    n.nspname                                                   AS schema_name,
    c.relname                                                   AS table_name,
    i.relname                                                   AS index_name,
    pg_size_pretty(pg_relation_size(i.oid))                      AS wasted_size,
    pg_get_indexdef(ix.indexrelid)                               AS index_definition
FROM pg_index ix
JOIN pg_class c ON c.oid = ix.indrelid
JOIN pg_class i ON i.oid = ix.indexrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE NOT ix.indisvalid
ORDER BY pg_relation_size(i.oid) DESC;
