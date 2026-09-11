/*
===============================================================================
SCRIPT NAME:
03_failure_context_and_settings.sql

PURPOSE:
Gathers the timeout settings and current lock picture that explain why the build failed, so the retry does not repeat it.

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
Step 03 of workflow 'schema-changes/failed-index-build'

RELATED SCRIPTS:
04_cleanup_invalid_index_runbook.md

HOW TO INTERPRET RESULTS:
Work through the likely causes in order. A non-zero statement_timeout or transaction_timeout in effect for the build session is the most common and most easily fixed cause -- and remember these can be set at role or database level, not only in the cluster parameter group, so a session inheriting a role default is a frequent surprise. A small maintenance_work_mem means the build spilled its sort to local storage, which both slows it down and risks exhausting local storage on the instance. The lock-wait result set shows whether DDL-style locks are currently queued on the table, which would indicate the build was competing with other schema changes or with autovacuum. If none of these explain it, check whether an Aurora failover or instance restart coincided with the build, which aborts it unconditionally.
===============================================================================
*/

-- The settings that determine how a DDL statement behaves when it cannot
-- get its lock immediately, and how much memory/parallelism an index build
-- gets. Always confirm these BEFORE issuing DDL against a busy production
-- table: a DDL statement with no lock_timeout that queues behind a
-- long-running transaction will itself block every subsequent query on the
-- table, converting a single slow statement into a full application outage.
--
-- On Aurora these are set through the DB cluster/instance parameter group,
-- not postgresql.conf; `source` tells you whether the current value came
-- from the parameter group (configuration file), a session-level SET, or
-- the built-in default.
SELECT
    name,
    setting,
    unit,
    context,
    source,
    short_desc
FROM pg_settings
WHERE name IN (
    'lock_timeout', 'statement_timeout', 'transaction_timeout',
    'idle_in_transaction_session_timeout', 'deadlock_timeout',
    'log_lock_waits', 'maintenance_work_mem',
    'max_parallel_maintenance_workers', 'max_locks_per_transaction',
    'default_transaction_read_only', 'default_statistics_target'
)
ORDER BY name;

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
