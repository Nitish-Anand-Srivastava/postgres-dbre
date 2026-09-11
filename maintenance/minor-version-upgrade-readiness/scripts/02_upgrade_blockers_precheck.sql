/*
===============================================================================
SCRIPT NAME:
02_upgrade_blockers_precheck.sql

PURPOSE:
Checks the three in-database conditions that most often block or complicate an engine upgrade: prepared transactions, replication slots, and long-running transactions.

AURORA POSTGRESQL VERSION:
Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise)

EXECUTION LOCATION:
Writer instance only (the query reads/writes state that only exists or is meaningful on the writer)

SAFETY:
READ ONLY

EXPECTED IMPACT:
Minimal -- reads system catalogs/statistics views only, no table locks beyond a brief catalog lookup.

REQUIRED PRIVILEGES:
Role membership in `pg_monitor` (or `pg_read_all_stats`) is sufficient. No superuser required.

PREREQUISITES:
None beyond CONNECT on the target database.

EXECUTION ORDER:
Step 02 of workflow 'maintenance/minor-version-upgrade-readiness'

RELATED SCRIPTS:
03_extension_and_settings_upgrade_surface.sql

HOW TO INTERPRET RESULTS:
Treat any prepared transaction as a hard blocker: it must be committed or rolled back by its owning service before the window (see transactions-and-xid/prepared-transactions). An inactive replication slot is a decision to make deliberately before the window rather than during it -- a stopped DMS task or retired CDC consumer should be retired properly, and a slot whose consumer is genuinely returning should be left alone and its WAL retention accounted for. A long-running transaction still open when the window starts will simply be terminated by the reboot, so the question is which business process loses its work, not whether the upgrade can proceed.
===============================================================================
*/

-- Outstanding two-phase-commit (PREPARE TRANSACTION) entries. These hold
-- locks and prevent vacuum from advancing past their snapshot until they
-- are COMMIT PREPARED / ROLLBACK PREPARED. Aurora PostgreSQL supports
-- two-phase commit, but very few application frameworks intentionally use
-- it -- an unexpected non-empty result here is almost always a bug in a
-- distributed-transaction coordinator (e.g. XA-style ORM configuration)
-- rather than expected behavior.
SELECT
    gid,
    prepared,
    owner,
    database,
    now() - prepared                                            AS prepared_age
FROM pg_prepared_xacts
ORDER BY prepared ASC;

-- Physical and logical replication slots, and whether they are actively
-- consumed. An inactive slot with a growing (restart_lsn falling behind
-- current WAL) footprint will hold WAL on disk indefinitely and, on Aurora,
-- can contribute to storage growth and volume I/O -- this is one of the
-- most common causes of unexplained storage growth on Aurora clusters that
-- use logical replication or CDC (e.g. Debezium, DMS).
--
-- IMPORTANT (verified against Aurora PostgreSQL 17.7): pg_current_wal_lsn()
-- is not available on Aurora -- detect Aurora first via a safe,
-- catalog/GUC-only check (never a call to an Aurora-only function itself,
-- so this never fails on non-Aurora PostgreSQL either) and never send a
-- statement referencing pg_current_wal_lsn() on the Aurora execution path.
-- wal_status alone (already reported either way) is enough to flag a slot
-- that has fallen dangerously behind ('lost'/'extended'); use CloudWatch or
-- aurora_replica_status() for byte-level WAL retention on Aurora.
SELECT (
    current_setting('aurora_version', true) IS NOT NULL
    OR current_setting('rds.extensions', true) IS NOT NULL
    OR EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'aurora_version')
)                                                                AS is_aurora
\gset

\if :is_aurora
SELECT
    slot_name,
    slot_type,
    plugin,
    database,
    active,
    active_pid,
    wal_status,
    restart_lsn,
    confirmed_flush_lsn,
    NULL::numeric                                                 AS retained_wal_bytes
FROM pg_replication_slots
ORDER BY slot_name;
\else
SELECT
    slot_name,
    slot_type,
    plugin,
    database,
    active,
    active_pid,
    wal_status,
    restart_lsn,
    confirmed_flush_lsn,
    pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)            AS retained_wal_bytes
FROM pg_replication_slots
ORDER BY retained_wal_bytes DESC NULLS LAST;
\endif

-- Transactions (not just active queries) open longer than :min_minutes
-- minutes, ordered by age. A transaction can be "idle in transaction" or
-- actively running a query and still be the oldest open transaction on the
-- instance -- which is what actually matters for vacuum horizon and lock
-- retention, not just the current query's runtime.
\set min_minutes 5
SELECT
    pid,
    datname,
    usename,
    state,
    backend_xid,
    backend_xmin,
    now() - xact_start                                          AS txn_age,
    left(query, 160)                                             AS current_or_last_query
FROM pg_stat_activity
WHERE xact_start IS NOT NULL
  AND now() - xact_start > make_interval(mins => :min_minutes)
ORDER BY txn_age DESC;
