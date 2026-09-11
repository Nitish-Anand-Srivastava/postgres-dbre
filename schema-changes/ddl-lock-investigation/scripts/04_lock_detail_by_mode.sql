/*
===============================================================================
SCRIPT NAME:
04_lock_detail_by_mode.sql

PURPOSE:
Provides the raw ground truth of who holds what lock, in which mode, on which object.

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
Step 04 of workflow 'schema-changes/ddl-lock-investigation'

RELATED SCRIPTS:
05_long_running_and_idle_transactions.sql

HOW TO INTERPRET RESULTS:
This is the authoritative view when the higher-level scripts disagree or the picture is confusing. Ungranted requests are listed first, which reconstructs the queue order directly. Match the mode column against what you expect: AccessExclusiveLock from most ALTER TABLE forms, plain DROP INDEX, TRUNCATE, REINDEX and VACUUM FULL; ShareUpdateExclusiveLock from the concurrent index operations, VALIDATE CONSTRAINT and autovacuum; ShareLock from a plain CREATE INDEX. If the blocker turns out to be an autovacuum worker, check whether it is an anti-wraparound vacuum before considering any action -- ordinary autovacuum yields to a conflicting lock request, but anti-wraparound does not and must never be cancelled to unblock a schema change.
===============================================================================
*/

-- Raw pg_locks detail joined to pg_stat_activity, restricted to relation and
-- transactionid locks that are either not yet granted or held by a session
-- that is also blocking someone else. This is the ground truth for "who
-- holds what lock, in what mode, on what object".
SELECT
    l.pid,
    a.usename,
    l.locktype,
    n.nspname                                                   AS schema_name,
    c.relname                                                    AS relation_name,
    l.mode,
    l.granted,
    a.state,
    now() - a.query_start                                        AS held_or_waiting_duration,
    left(a.query, 160)                                           AS query_snippet
FROM pg_locks l
LEFT JOIN pg_class c ON c.oid = l.relation
LEFT JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_stat_activity a ON a.pid = l.pid
WHERE l.pid <> pg_backend_pid()
  AND l.locktype IN ('relation', 'tuple', 'transactionid')
ORDER BY l.granted ASC, held_or_waiting_duration DESC NULLS LAST;
