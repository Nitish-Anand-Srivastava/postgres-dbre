/*
===============================================================================
SCRIPT NAME:
06_post_build_validation.sql

PURPOSE:
Confirms after the build that the index is valid, that no build is still running, and that nothing was left behind.

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
Step 06 of workflow 'schema-changes/safe-index-creation'

RELATED SCRIPTS:
../failed-index-build/README.md

HOW TO INTERPRET RESULTS:
The first result set must be empty for the table you just built against. Any row for your new index means the build did not complete successfully and left an INVALID index behind -- it consumes full storage and full write overhead while the planner ignores it entirely, so it must be dropped through the failed-index-build workflow before you retry. The second result set shows any index build still in progress; if your build appears there, it has not finished yet and you should keep monitoring rather than declaring success. Once the index is confirmed valid, verify over the following days that the query it was built for actually picks it up -- an index that is never scanned is a permanent write-amplification cost with no benefit.
===============================================================================
*/

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
