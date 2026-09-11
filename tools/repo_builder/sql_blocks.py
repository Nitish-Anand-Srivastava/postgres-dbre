"""Library of real, PostgreSQL 17 / Aurora PostgreSQL compatible SQL query
bodies shared across workflow definitions.

Every function returns a complete, standalone SQL query (or short sequence of
`\\set` + query) as a string. The generator composes these bodies with a
per-workflow header (purpose/safety/interpretation) defined in the workflow
registry, so the same underlying, verified catalog query can be reused across
several workflows with different framing -- this is the "duplication over
false-DRY coupling" pattern the specification calls for, while keeping the
actual SQL centrally correct and easy to fix in one place.

All queries here:
  * are read-only (SELECT only, no data-modifying statements),
  * avoid SELECT * (explicit column lists everywhere, with a documented
    exception for Aurora-specific functions whose column set is genuinely
    version-dependent),
  * use NULLIF / CASE guards to avoid divide-by-zero,
  * avoid catalog columns that do not exist on PostgreSQL 17
    (e.g. pg_stat_progress_vacuum uses the PG17 max_dead_tuple_bytes /
    dead_tuple_bytes / indexes_total / indexes_processed columns, and
    checkpoint counters are read from pg_stat_checkpointer, not
    pg_stat_bgwriter, per the PG17 statistics split),
  * assume only pg_monitor / pg_read_all_stats-level privileges unless a
    script's own header states otherwise.
"""
from __future__ import annotations


def psql_vars(defs: str) -> str:
    """Render a block of documented psql \\set variable defaults.

    ``defs`` is a string of ``name=default=comment`` lines separated by ';'.
    Kept intentionally simple (no templating engine) so the generated SQL
    stays fully readable in a plain psql session.
    """
    return defs


# ---------------------------------------------------------------------------
# Sessions / activity
# ---------------------------------------------------------------------------

def activity_overview() -> str:
    return """
-- Snapshot of every backend known to this instance right now, grouped by
-- high-level state. Run this first on any performance or availability
-- investigation to understand overall load before drilling into detail.
SELECT
    datname,
    state,
    wait_event_type,
    count(*)                                                   AS session_count,
    count(*) FILTER (WHERE state = 'active')                   AS active_count,
    max(now() - query_start)                                   AS longest_query_runtime,
    max(now() - xact_start)                                    AS longest_txn_runtime
FROM pg_stat_activity
WHERE pid <> pg_backend_pid()
GROUP BY datname, state, wait_event_type
ORDER BY session_count DESC, longest_query_runtime DESC NULLS LAST;
""".strip("\n")


def active_long_running_queries() -> str:
    return """
-- Active queries currently running longer than :min_seconds seconds.
-- Adjust :min_seconds for your workload's normal latency profile; a
-- crypto-exchange OLTP path is typically sub-100ms, so even a handful of
-- seconds may already indicate a problem.
\\set min_seconds 5
SELECT
    pid,
    datname,
    usename,
    application_name,
    client_addr,
    state,
    wait_event_type,
    wait_event,
    backend_xid,
    backend_xmin,
    now() - query_start                                        AS query_runtime,
    now() - xact_start                                          AS txn_runtime,
    left(query, 200)                                            AS query_snippet
FROM pg_stat_activity
WHERE state = 'active'
  AND pid <> pg_backend_pid()
  AND now() - query_start > make_interval(secs => :min_seconds)
ORDER BY query_runtime DESC;
""".strip("\n")


def idle_in_transaction_sessions() -> str:
    return """
-- Sessions sitting idle inside an open transaction for longer than
-- :min_minutes minutes. These hold open snapshots/locks and are a very
-- common cause of autovacuum being unable to clean up dead tuples, and of
-- unexpected lock waits on otherwise unrelated statements.
\\set min_minutes 5
SELECT
    pid,
    datname,
    usename,
    application_name,
    client_addr,
    state,
    backend_xid,
    backend_xmin,
    now() - xact_start                                          AS idle_txn_duration,
    now() - state_change                                        AS time_in_current_state,
    left(query, 200)                                             AS last_statement
FROM pg_stat_activity
WHERE state = 'idle in transaction'
  AND pid <> pg_backend_pid()
  AND now() - state_change > make_interval(mins => :min_minutes)
ORDER BY idle_txn_duration DESC;
""".strip("\n")


def wait_events_summary() -> str:
    return """
-- Aggregated wait events across all current backends. PostgreSQL 17 exposes
-- a canonical description of every wait event in pg_wait_events -- join to
-- it so unfamiliar wait_event values are self-explanatory without needing
-- the manual open.
SELECT
    a.wait_event_type,
    a.wait_event,
    we.description,
    count(*)                                                    AS backend_count
FROM pg_stat_activity a
LEFT JOIN pg_wait_events we
       ON we.type = a.wait_event_type
      AND we.name = a.wait_event
WHERE a.pid <> pg_backend_pid()
  AND a.wait_event IS NOT NULL
GROUP BY a.wait_event_type, a.wait_event, we.description
ORDER BY backend_count DESC;
""".strip("\n")


def connections_by_state() -> str:
    return """
-- Connection counts by database and state, compared against max_connections
-- so the operator can see headroom immediately.
SELECT
    coalesce(datname, '(no database / background worker)')     AS datname,
    state,
    count(*)                                                    AS session_count,
    round(
        100.0 * count(*) / NULLIF((SELECT setting::numeric FROM pg_settings WHERE name = 'max_connections'), 0),
        2
    )                                                            AS pct_of_max_connections
FROM pg_stat_activity
GROUP BY datname, state
ORDER BY session_count DESC;
""".strip("\n")


def connections_by_application_and_user() -> str:
    return """
-- Connection counts broken down by application_name and usename. Useful to
-- identify which service, connection pool, or batch job is responsible for
-- a spike or leak in connection count.
SELECT
    coalesce(NULLIF(application_name, ''), '(unset)')           AS application_name,
    usename,
    datname,
    count(*)                                                    AS session_count,
    count(*) FILTER (WHERE state = 'active')                    AS active_count,
    count(*) FILTER (WHERE state = 'idle')                      AS idle_count,
    count(*) FILTER (WHERE state = 'idle in transaction')       AS idle_in_txn_count
FROM pg_stat_activity
WHERE pid <> pg_backend_pid()
GROUP BY application_name, usename, datname
ORDER BY session_count DESC;
""".strip("\n")


def max_connections_headroom() -> str:
    return """
-- Current connection utilization vs. the effective connection ceiling.
-- On Aurora, max_connections is derived from the instance class's memory
-- (via the parameter group formula) rather than freely set, so headroom
-- must be planned around instance class, not just the GUC value alone.
SELECT
    (SELECT setting::int FROM pg_settings WHERE name = 'max_connections')      AS max_connections,
    (SELECT setting::int FROM pg_settings WHERE name = 'superuser_reserved_connections') AS superuser_reserved,
    (SELECT count(*) FROM pg_stat_activity)                                    AS current_total_connections,
    (SELECT count(*) FROM pg_stat_activity WHERE state = 'active')             AS current_active_connections,
    round(
        100.0 * (SELECT count(*) FROM pg_stat_activity) /
        NULLIF((SELECT setting::numeric FROM pg_settings WHERE name = 'max_connections'), 0),
        2
    )                                                                          AS pct_utilized;
""".strip("\n")


# ---------------------------------------------------------------------------
# Locks / blocking / concurrency
# ---------------------------------------------------------------------------

def blocked_sessions() -> str:
    return """
-- Every session currently blocked waiting on at least one lock, and the
-- pid(s) directly blocking it via the built-in pg_blocking_pids() helper
-- (this correctly follows lock-wait-queue order, unlike a naive self-join
-- on pg_locks).
SELECT
    blocked.pid                                                 AS blocked_pid,
    blocked.usename                                              AS blocked_user,
    blocked.datname                                              AS blocked_database,
    blocked.state                                                AS blocked_state,
    now() - blocked.query_start                                  AS blocked_duration,
    pg_blocking_pids(blocked.pid)                                AS blocking_pids,
    left(blocked.query, 200)                                     AS blocked_query
FROM pg_stat_activity blocked
WHERE cardinality(pg_blocking_pids(blocked.pid)) > 0
ORDER BY blocked_duration DESC;
""".strip("\n")


def blocking_sessions_detail() -> str:
    return """
-- For every blocked session, expand pg_blocking_pids() into one row per
-- blocker and show what the blocker itself is doing, so the operator can
-- decide whether to wait, escalate, or (rarely, and only if authorized)
-- terminate the blocking backend.
SELECT
    blocked.pid                                                 AS blocked_pid,
    blocked.usename                                              AS blocked_user,
    left(blocked.query, 120)                                     AS blocked_query,
    blocker.pid                                                  AS blocking_pid,
    blocker.usename                                              AS blocking_user,
    blocker.state                                                AS blocking_state,
    now() - blocker.xact_start                                   AS blocking_txn_age,
    left(blocker.query, 120)                                     AS blocking_last_query
FROM pg_stat_activity blocked
CROSS JOIN LATERAL unnest(pg_blocking_pids(blocked.pid)) AS bp(blocking_pid)
JOIN pg_stat_activity blocker ON blocker.pid = bp.blocking_pid
ORDER BY blocking_txn_age DESC;
""".strip("\n")


def lock_detail_by_mode() -> str:
    return """
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
""".strip("\n")


def ddl_lock_waits() -> str:
    return """
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
""".strip("\n")


def long_running_transactions() -> str:
    return """
-- Transactions (not just active queries) open longer than :min_minutes
-- minutes, ordered by age. A transaction can be "idle in transaction" or
-- actively running a query and still be the oldest open transaction on the
-- instance -- which is what actually matters for vacuum horizon and lock
-- retention, not just the current query's runtime.
\\set min_minutes 5
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
""".strip("\n")


def deadlock_counters_by_database() -> str:
    return """
-- Cumulative deadlock counters per database since the last stats reset.
-- This does not show individual deadlock events (those are only visible in
-- the PostgreSQL log with log_lock_waits / deadlock_timeout logging, which
-- on Aurora is surfaced through CloudWatch Logs for the instance), but a
-- rising counter confirms deadlocks are actually occurring and lets you
-- correlate the timing with an incident window.
SELECT
    datname,
    deadlocks,
    xact_commit,
    xact_rollback,
    round(100.0 * deadlocks / NULLIF(xact_commit + xact_rollback, 0), 4) AS deadlocks_per_100_txn,
    stats_reset
FROM pg_stat_database
WHERE datname IS NOT NULL
ORDER BY deadlocks DESC;
""".strip("\n")


def connection_contention_by_wait_event() -> str:
    return """
-- Backends waiting specifically on Lock/IPC/Client wait event types,
-- summarized to distinguish "too many app connections queuing for locks"
-- from "connections idle waiting on client round trips" (often a pooler or
-- application-side issue rather than a database issue).
SELECT
    wait_event_type,
    wait_event,
    state,
    count(*)                                                    AS backend_count,
    max(now() - state_change)                                   AS longest_time_in_state
FROM pg_stat_activity
WHERE pid <> pg_backend_pid()
GROUP BY wait_event_type, wait_event, state
ORDER BY backend_count DESC;
""".strip("\n")


# ---------------------------------------------------------------------------
# Transactions / XID / multixact
# ---------------------------------------------------------------------------

def database_transaction_age() -> str:
    return """
-- Transaction ID (XID) age per database, measured against datfrozenxid.
-- autovacuum_freeze_max_age (default 200,000,000) is the point at which
-- autovacuum is forced to run in every table regardless of cost limits;
-- autovacuum_vacuum_freeze_min_age / vacuum_failsafe_age (default
-- 1,600,000,000) is the emergency threshold before wraparound-protection
-- kicks in and PostgreSQL refuses new writes to protect data integrity.
SELECT
    datname,
    age(datfrozenxid)                                           AS xid_age,
    datfrozenxid,
    round(
        100.0 * age(datfrozenxid) /
        (SELECT setting::numeric FROM pg_settings WHERE name = 'autovacuum_freeze_max_age'),
        2
    )                                                            AS pct_of_freeze_max_age,
    2147483647 - age(datfrozenxid)                                AS xids_remaining_to_wraparound
FROM pg_database
WHERE datallowconn
ORDER BY xid_age DESC;
""".strip("\n")


def table_transaction_age_top_n() -> str:
    return """
-- Per-table XID age ranked descending, restricted to ordinary tables and
-- materialized views (relkind 'r'/'m'/'t' -- includes TOAST tables, which
-- can independently accumulate age and are frequently overlooked).
\\set top_n 25
SELECT
    n.nspname                                                   AS schema_name,
    c.relname                                                   AS relation_name,
    c.relkind,
    age(c.relfrozenxid)                                         AS xid_age,
    c.relfrozenxid,
    pg_size_pretty(pg_total_relation_size(c.oid))                AS total_size
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'm', 't')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY xid_age DESC
LIMIT :top_n;
""".strip("\n")


def multixact_age_top_n() -> str:
    return """
-- Per-table multixact ID age (relminmxid), which tracks a separate
-- wraparound horizon from relfrozenxid. Row-level locking (SELECT ... FOR
-- UPDATE/SHARE, foreign key checks) generates multixacts, so tables with
-- heavy row locking (order books, balances, ledgers) can accumulate
-- multixact age even when regular XID age looks healthy.
\\set top_n 25
SELECT
    n.nspname                                                   AS schema_name,
    c.relname                                                   AS relation_name,
    mxid_age(c.relminmxid)                                      AS multixact_age,
    c.relminmxid,
    round(
        100.0 * mxid_age(c.relminmxid) /
        (SELECT setting::numeric FROM pg_settings WHERE name = 'autovacuum_multixact_freeze_max_age'),
        2
    )                                                            AS pct_of_multixact_freeze_max_age
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'm', 't')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY multixact_age DESC
LIMIT :top_n;
""".strip("\n")


def prepared_transactions() -> str:
    return """
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
""".strip("\n")


def autovacuum_workers_active() -> str:
    return """
-- Autovacuum (and manual VACUUM/ANALYZE) workers currently running, and
-- what phase they are in via pg_stat_progress_vacuum. On PG17 the dead
-- tuple counters are reported in bytes (max_dead_tuple_bytes /
-- dead_tuple_bytes), not tuple counts, reflecting the new TID-store based
-- vacuum implementation.
SELECT
    a.pid,
    a.datname,
    n.nspname                                                    AS schema_name,
    c.relname                                                    AS relation_name,
    v.phase,
    v.heap_blks_total,
    v.heap_blks_scanned,
    round(100.0 * v.heap_blks_scanned / NULLIF(v.heap_blks_total, 0), 2) AS pct_heap_scanned,
    v.indexes_total,
    v.indexes_processed,
    pg_size_pretty(v.dead_tuple_bytes)                            AS dead_tuple_data_collected,
    pg_size_pretty(v.max_dead_tuple_bytes)                        AS dead_tuple_data_limit,
    now() - a.xact_start                                          AS running_for
FROM pg_stat_progress_vacuum v
JOIN pg_stat_activity a ON a.pid = v.pid
LEFT JOIN pg_class c ON c.oid = v.relid
LEFT JOIN pg_namespace n ON n.oid = c.relnamespace
ORDER BY running_for DESC;
""".strip("\n")


def replication_slots_status() -> str:
    return """
-- Physical and logical replication slots, and whether they are actively
-- consumed. An inactive slot with a growing (restart_lsn falling behind
-- current WAL) footprint will hold WAL on disk indefinitely and, on Aurora,
-- can contribute to storage growth and volume I/O -- this is one of the
-- most common causes of unexplained storage growth on Aurora clusters that
-- use logical replication or CDC (e.g. Debezium, DMS).
--
-- IMPORTANT (verified against Aurora PostgreSQL 17.7): pg_current_wal_lsn()
-- errors on Aurora clusters running with wal_level=replica (Aurora's
-- default) -- guarded here via a current_setting('wal_level') CASE check
-- (only evaluates its matching branch, the same mechanism used to avoid
-- division-by-zero in a CASE), computed once in a CTE and reused, so the
-- function is never actually invoked unless wal_level is already 'logical'.
WITH current_position AS (
    SELECT CASE WHEN current_setting('wal_level') = 'logical'
                THEN pg_current_wal_lsn()
                ELSE NULL
           END AS lsn
)
SELECT
    s.slot_name,
    s.slot_type,
    s.plugin,
    s.database,
    s.active,
    s.active_pid,
    s.wal_status,
    s.restart_lsn,
    s.confirmed_flush_lsn,
    CASE WHEN c.lsn IS NOT NULL
         THEN pg_wal_lsn_diff(c.lsn, s.restart_lsn)
         ELSE NULL
    END                                                            AS retained_wal_bytes
FROM pg_replication_slots s
CROSS JOIN current_position c
ORDER BY retained_wal_bytes DESC NULLS LAST;
""".strip("\n")


# ---------------------------------------------------------------------------
# Vacuum / bloat / statistics
# ---------------------------------------------------------------------------

def dead_tuples_ranked() -> str:
    return """
-- Tables ranked by dead tuple ratio and absolute dead tuple count. High
-- dead-tuple ratios combined with a stale last_autovacuum timestamp are the
-- clearest sign that autovacuum is not keeping up with a table's write rate.
\\set top_n 30
SELECT
    schemaname                                                  AS schema_name,
    relname                                                     AS table_name,
    n_live_tup,
    n_dead_tup,
    round(100.0 * n_dead_tup / NULLIF(n_live_tup + n_dead_tup, 0), 2) AS dead_tuple_pct,
    last_vacuum,
    last_autovacuum,
    last_analyze,
    last_autoanalyze,
    autovacuum_count,
    vacuum_count
FROM pg_stat_all_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY n_dead_tup DESC
LIMIT :top_n;
""".strip("\n")


def table_bloat_estimate() -> str:
    return """
-- Lightweight, catalog-only bloat proxy: live/dead tuple ratio plus actual
-- on-disk size vs. a rough expectation from reltuples. This is NOT as
-- accurate as the pgstattuple extension's exact physical scan, but it
-- requires no extension and no table lock, so it is safe to run against any
-- table at any time -- use it for triage, and use pgstattuple (see
-- 05_pgstattuple_exact_bloat.sql in this same directory, if present) for
-- confirmation before scheduling a maintenance window.
SELECT
    n.nspname                                                   AS schema_name,
    c.relname                                                   AS table_name,
    pg_size_pretty(pg_relation_size(c.oid))                      AS heap_size,
    pg_size_pretty(pg_total_relation_size(c.oid))                 AS total_size,
    s.n_live_tup,
    s.n_dead_tup,
    round(100.0 * s.n_dead_tup / NULLIF(s.n_live_tup + s.n_dead_tup, 0), 2) AS dead_tuple_pct,
    c.reltuples::bigint                                          AS planner_row_estimate,
    c.relpages                                                   AS heap_pages
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_stat_all_tables s ON s.relid = c.oid
WHERE c.relkind = 'r'
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY pg_total_relation_size(c.oid) DESC
LIMIT 30;
""".strip("\n")


def pgstattuple_exact_bloat() -> str:
    return """
-- Exact physical bloat via the pgstattuple extension, for the single
-- largest ordinary user table in the current database (a bounded,
-- automatic candidate -- edit the candidate_relation query below to target
-- a specific table instead). Performs a full scan of that table (a light
-- read lock, not a blocking lock) -- do not run this against your largest
-- hot tables during peak trading hours without testing impact first;
-- prefer pgstattuple_approx() for very large tables.
--
-- IMPORTANT: this script deliberately does NOT run `CREATE EXTENSION
-- pgstattuple` -- that is a DDL/catalog-write operation that cannot execute
-- under `default_transaction_read_only = on` (the recommended posture for
-- an investigation script, and the default on an Aurora reader), and
-- installing extensions is a change-managed decision, not something an
-- ad hoc investigation script should do silently. If the extension is not
-- installed, this prints an instructional notice instead of failing, and
-- never references the pgstattuple() function by name unless the
-- extension is confirmed present -- referencing a function that does not
-- exist yet would otherwise fail at parse/analysis time even inside a
-- branch that "looks" conditional.
SELECT EXISTS (
    SELECT 1 FROM pg_extension WHERE extname = 'pgstattuple'
)                                                                AS pgstattuple_available
\\gset

\\if :pgstattuple_available
SELECT c.oid::regclass::text AS candidate_relation
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'r'
  AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
ORDER BY pg_total_relation_size(c.oid) DESC
LIMIT 1
\\gset

SELECT
    :'candidate_relation'                                       AS table_analyzed,
    table_len,
    tuple_count,
    tuple_len,
    round(100.0 * tuple_len / NULLIF(table_len, 0), 2)            AS tuple_pct,
    dead_tuple_count,
    dead_tuple_len,
    round(100.0 * dead_tuple_len / NULLIF(table_len, 0), 2)       AS dead_tuple_pct,
    free_space,
    round(100.0 * free_space / NULLIF(table_len, 0), 2)           AS free_pct
FROM pgstattuple(:'candidate_relation'::regclass);
\\else
SELECT
    'pgstattuple extension is not installed in this database. This script '
    'never runs CREATE EXTENSION automatically (DDL is out of scope for a '
    'read-only investigation script). Ask an administrator to run '
    'CREATE EXTENSION pgstattuple; in a change-managed session if exact '
    'physical bloat is required, or use 01_table_bloat_estimate.sql in this '
    'same directory for a no-extension catalog-only proxy.'               AS notice;
\\endif
""".strip("\n")


def index_bloat_and_usage() -> str:
    return """
-- Index size, scan counts, and a simple size-per-row proxy for bloat.
-- PostgreSQL 16+ also reports last_idx_scan/last_idx_tup_fetch/
-- last_idx_tup_read (timestamps) on pg_stat_all_indexes, which are included
-- here to show *when* an index was last actually useful, not just whether
-- idx_scan is currently zero since the last stats reset.
\\set top_n 40
SELECT
    n.nspname                                                   AS schema_name,
    c.relname                                                   AS table_name,
    i.relname                                                   AS index_name,
    pg_size_pretty(pg_relation_size(i.oid))                      AS index_size,
    s.idx_scan,
    s.idx_tup_read,
    s.idx_tup_fetch,
    s.last_idx_scan,
    ix.indisunique,
    ix.indisprimary,
    ix.indisvalid
FROM pg_index ix
JOIN pg_class c ON c.oid = ix.indrelid
JOIN pg_class i ON i.oid = ix.indexrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_stat_all_indexes s ON s.indexrelid = ix.indexrelid
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY pg_relation_size(i.oid) DESC
LIMIT :top_n;
""".strip("\n")


def unused_indexes() -> str:
    return """
-- Candidate unused indexes: idx_scan = 0 (or very low relative to table
-- write volume) since the last stats reset, excluding indexes that back a
-- primary key, unique, exclusion, or foreign-key-supporting constraint,
-- since those often exist for correctness/latching reasons rather than
-- query performance and must not be dropped purely on scan-count evidence.
--
-- IMPORTANT: idx_scan resets to zero on instance restart/failover and after
-- pg_stat_reset(). Cross-check stats_reset on pg_stat_database and confirm
-- the index has genuinely been unused across at least one full business
-- cycle (including month-end/quarter-end batch jobs and reporting queries)
-- before considering removal. Never drop an index based on this report
-- alone.
SELECT
    n.nspname                                                   AS schema_name,
    c.relname                                                   AS table_name,
    i.relname                                                   AS index_name,
    pg_size_pretty(pg_relation_size(i.oid))                      AS index_size,
    s.idx_scan,
    ix.indisunique,
    ix.indisprimary,
    EXISTS (
        SELECT 1 FROM pg_constraint con
        WHERE con.conindid = ix.indexrelid
    )                                                            AS backs_constraint
FROM pg_index ix
JOIN pg_class c ON c.oid = ix.indrelid
JOIN pg_class i ON i.oid = ix.indexrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_stat_all_indexes s ON s.indexrelid = ix.indexrelid
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND s.idx_scan = 0
  AND NOT ix.indisprimary
  AND NOT EXISTS (SELECT 1 FROM pg_constraint con WHERE con.conindid = ix.indexrelid)
ORDER BY pg_relation_size(i.oid) DESC;
""".strip("\n")


def duplicate_indexes() -> str:
    return """
-- Indexes on the same table with identical column lists (indkey), access
-- method, and expression/predicate signature -- true structural duplicates
-- that waste storage and add write overhead without any query benefit.
-- Compares the human-readable index definition rather than raw indkey
-- arrays so expression indexes and partial indexes are also caught
-- correctly.
SELECT
    n.nspname                                                    AS schema_name,
    c.relname                                                    AS table_name,
    array_agg(i.relname ORDER BY i.relname)                       AS duplicate_index_names,
    min(regexp_replace(pg_get_indexdef(ix.indexrelid), 'INDEX [^ ]+ ', 'INDEX ', 1, 1)) AS normalized_definition,
    count(*)                                                     AS duplicate_count,
    pg_size_pretty(sum(pg_relation_size(i.oid)))                  AS combined_size
FROM pg_index ix
JOIN pg_class c ON c.oid = ix.indrelid
JOIN pg_class i ON i.oid = ix.indexrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
GROUP BY n.nspname, c.relname, ix.indrelid,
         regexp_replace(pg_get_indexdef(ix.indexrelid), 'INDEX [^ ]+ ', 'INDEX ', 1, 1)
HAVING count(*) > 1
ORDER BY combined_size DESC;
""".strip("\n")


def invalid_indexes() -> str:
    return """
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
""".strip("\n")


def sequential_scan_heavy_tables() -> str:
    return """
-- Tables where sequential scans dominate over index scans, weighted by
-- table size, to prioritize the biggest opportunity first. A high seq_scan
-- count alone is not necessarily bad (small lookup tables are often scanned
-- sequentially by design and that is faster than an index scan) -- the
-- seq_tup_read/seq_scan ratio and table size are what indicate a genuinely
-- expensive full-table scan pattern.
\\set top_n 30
SELECT
    schemaname                                                  AS schema_name,
    relname                                                     AS table_name,
    seq_scan,
    seq_tup_read,
    round(seq_tup_read::numeric / NULLIF(seq_scan, 0), 0)         AS avg_rows_per_seq_scan,
    idx_scan,
    pg_size_pretty(pg_relation_size(relid))                       AS table_size,
    n_live_tup
FROM pg_stat_all_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
  AND seq_scan > 0
ORDER BY seq_tup_read DESC
LIMIT :top_n;
""".strip("\n")


def foreign_keys_missing_index() -> str:
    return """
-- Foreign key constraints whose referencing columns have no supporting
-- index on the child table. Unindexed FKs commonly cause full-table
-- sequential scans on the child table whenever the parent row is updated or
-- deleted (to check for dependents) and are one of the most common
-- "missing index candidate" findings in ledger/order/account schemas with
-- deep FK graphs.
SELECT
    con.conname                                                 AS constraint_name,
    tn.nspname                                                  AS child_schema,
    tc.relname                                                  AS child_table,
    pg_get_constraintdef(con.oid)                                AS constraint_definition
FROM pg_constraint con
JOIN pg_class tc ON tc.oid = con.conrelid
JOIN pg_namespace tn ON tn.oid = tc.relnamespace
WHERE con.contype = 'f'
  AND NOT EXISTS (
      SELECT 1
      FROM pg_index ix
      WHERE ix.indrelid = con.conrelid
        -- Leftmost-prefix match: the index's first N columns (N = number of
        -- FK columns) must exactly equal the FK's referencing columns, in
        -- the same order, for the index to actually support the FK's
        -- lookup/cascade pattern.
        AND (ix.indkey::int2[])[0:array_length(con.conkey, 1) - 1] = con.conkey
  )
ORDER BY child_schema, child_table;
""".strip("\n")


def statistics_freshness() -> str:
    return """
-- Tables whose planner statistics may be stale relative to how much the
-- table has changed since the last ANALYZE. n_mod_since_analyze counts
-- inserts+updates+deletes since the last analyze; a large value relative to
-- table size means the planner's row estimates (and therefore its join
-- order / index choice) can be significantly wrong.
\\set top_n 30
SELECT
    schemaname                                                  AS schema_name,
    relname                                                     AS table_name,
    n_live_tup,
    n_mod_since_analyze,
    round(100.0 * n_mod_since_analyze / NULLIF(n_live_tup, 0), 2) AS pct_modified_since_analyze,
    last_analyze,
    last_autoanalyze
FROM pg_stat_all_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY pct_modified_since_analyze DESC NULLS LAST
LIMIT :top_n;
""".strip("\n")


# ---------------------------------------------------------------------------
# pg_stat_statements
# ---------------------------------------------------------------------------

def pgss_top_by_total_time() -> str:
    return """
-- Top statements by total execution time -- the single best "where is the
-- database spending its time" view. Requires the pg_stat_statements
-- extension to be created in the current database and
-- shared_preload_libraries to include pg_stat_statements at the cluster
-- level (an Aurora/RDS parameter-group change requiring a reboot to apply).
\\set top_n 20
SELECT
    userid::regrole                                             AS run_as_role,
    queryid,
    calls,
    round(total_exec_time::numeric, 2)                            AS total_exec_time_ms,
    round(mean_exec_time::numeric, 2)                             AS mean_exec_time_ms,
    rows,
    round(100.0 * shared_blks_hit / NULLIF(shared_blks_hit + shared_blks_read, 0), 2) AS cache_hit_pct,
    temp_blks_written,
    left(query, 200)                                              AS query_snippet
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
ORDER BY total_exec_time DESC
LIMIT :top_n;
""".strip("\n")


def pgss_top_by_mean_time() -> str:
    return """
-- Top statements by mean execution time, restricted to statements called at
-- least :min_calls times so a single slow one-off migration query does not
-- crowd out genuinely slow, frequently-run application queries.
\\set top_n 20
\\set min_calls 20
SELECT
    queryid,
    calls,
    round(mean_exec_time::numeric, 2)                             AS mean_exec_time_ms,
    round(stddev_exec_time::numeric, 2)                           AS stddev_exec_time_ms,
    round(max_exec_time::numeric, 2)                              AS max_exec_time_ms,
    rows,
    left(query, 200)                                              AS query_snippet
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
  AND calls >= :min_calls
ORDER BY mean_exec_time DESC
LIMIT :top_n;
""".strip("\n")


def pgss_top_by_calls() -> str:
    return """
-- Top statements by call frequency. Extremely high-frequency, low-latency
-- statements are exactly what you expect for an OLTP/order-book workload;
-- the interesting signal is a sudden large increase in calls for a given
-- queryid between two snapshots (application retry storm, N+1 query
-- pattern, or a newly deployed hot loop), so save this output and diff it
-- across incidents.
\\set top_n 20
SELECT
    queryid,
    calls,
    round(total_exec_time::numeric, 2)                            AS total_exec_time_ms,
    round(mean_exec_time::numeric, 4)                             AS mean_exec_time_ms,
    rows,
    left(query, 200)                                              AS query_snippet
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
ORDER BY calls DESC
LIMIT :top_n;
""".strip("\n")


def pgss_temp_and_io_heavy() -> str:
    return """
-- Statements generating the most temp file I/O and shared buffer reads --
-- a direct indicator of work_mem being too small for a sort/hash/group-by,
-- or of a query reading far more data (a poor index choice, a missing
-- predicate) than a well-planned query should need.
--
-- IMPORTANT (verified against Aurora PostgreSQL 17.7): pg_stat_statements
-- 1.11, bundled with PostgreSQL/Aurora PostgreSQL 17, split the older
-- generic blk_read_time/blk_write_time columns into separate
-- shared/local/temp variants -- shared_blk_read_time, shared_blk_write_time,
-- local_blk_read_time, local_blk_write_time, temp_blk_read_time,
-- temp_blk_write_time. The bare blk_read_time/blk_write_time column names
-- no longer exist at all on 17, so referencing them raises "column does
-- not exist" rather than returning zero. This script reads
-- shared_blk_read_time (the direct 1.11 successor covering ordinary shared
-- buffer reads, which is what this script is measuring) instead.
\\set top_n 20
SELECT
    queryid,
    calls,
    temp_blks_written,
    temp_blks_read,
    shared_blks_read,
    round(shared_blk_read_time::numeric, 2)                       AS shared_blk_read_time_ms,
    round(mean_exec_time::numeric, 2)                             AS mean_exec_time_ms,
    left(query, 200)                                              AS query_snippet
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
  AND (temp_blks_written > 0 OR temp_blks_read > 0)
ORDER BY temp_blks_written DESC
LIMIT :top_n;
""".strip("\n")


def pgss_wal_heavy() -> str:
    return """
-- Statements generating the most WAL, ranked by total WAL bytes. High
-- WAL-generating statements are the primary driver of replica lag (Aurora
-- readers must apply the same redo the writer generates) and of storage
-- growth; this is the first place to look when replication lag or storage
-- growth correlates with a specific workload rather than overall volume.
--
-- CAVEAT (observed on Aurora PostgreSQL 17.7): pg_stat_statements'
-- wal_records/wal_fpi/wal_bytes columns have been observed reporting 0 for
-- some write-heavy INSERT/UPDATE statements, even though those statements
-- are demonstrably generating WAL (visible via pg_stat_wal / rising storage
-- growth). Treat a 0 here as "not observed via this instrumentation path
-- for this statement on this engine version" -- NOT as proof the statement
-- generates no WAL. Corroborate with storage-and-capacity/wal-generation
-- (cluster-wide pg_stat_wal totals) before concluding a specific statement
-- is WAL-cheap.
\\set top_n 20
SELECT
    queryid,
    calls,
    wal_records,
    wal_fpi,
    pg_size_pretty(wal_bytes)                                     AS total_wal,
    pg_size_pretty((wal_bytes / NULLIF(calls, 0))::bigint)         AS avg_wal_per_call,
    CASE WHEN wal_bytes = 0
         THEN 'zero reported -- not observed/unavailable on this engine version, not proof of no WAL (see script header)'
         ELSE NULL
    END                                                            AS wal_reporting_caveat,
    left(query, 200)                                              AS query_snippet
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
ORDER BY wal_bytes DESC
LIMIT :top_n;
""".strip("\n")


# ---------------------------------------------------------------------------
# Sizing / storage / WAL / checkpoints
# ---------------------------------------------------------------------------

def database_sizes() -> str:
    return """
-- Size of every database in the cluster. On Aurora, this reflects logical
-- object size as PostgreSQL reports it; actual billed storage is tracked
-- separately by the Aurora storage layer (see AWS Console/CloudWatch
-- VolumeBytesUsed, not a SQL-visible value) because Aurora storage grows in
-- 10GiB increments and is shared/compressed across the cluster's
-- replicas.
SELECT
    datname,
    pg_size_pretty(pg_database_size(datname))                     AS database_size,
    pg_database_size(datname)                                     AS database_size_bytes
FROM pg_database
WHERE datallowconn
ORDER BY pg_database_size(datname) DESC;
""".strip("\n")


def largest_tables() -> str:
    return """
-- Largest tables in the current database by total size (heap + indexes +
-- TOAST), which is what actually matters for storage capacity planning and
-- I/O footprint.
\\set top_n 30
SELECT
    n.nspname                                                   AS schema_name,
    c.relname                                                   AS table_name,
    pg_size_pretty(pg_relation_size(c.oid))                       AS heap_size,
    pg_size_pretty(pg_indexes_size(c.oid))                        AS index_size,
    pg_size_pretty(pg_total_relation_size(c.oid))                 AS total_size,
    c.reltuples::bigint                                          AS estimated_row_count
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY pg_total_relation_size(c.oid) DESC
LIMIT :top_n;
""".strip("\n")


def largest_indexes() -> str:
    return """
\\set top_n 30
SELECT
    n.nspname                                                   AS schema_name,
    t.relname                                                    AS table_name,
    i.relname                                                    AS index_name,
    pg_size_pretty(pg_relation_size(i.oid))                       AS index_size
FROM pg_index ix
JOIN pg_class t ON t.oid = ix.indrelid
JOIN pg_class i ON i.oid = ix.indexrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY pg_relation_size(i.oid) DESC
LIMIT :top_n;
""".strip("\n")


def table_growth_rate_from_snapshot() -> str:
    return """
-- Table size growth over time requires two or more point-in-time samples.
-- This query assumes you are periodically appending
-- (now(), schemaname, relname, pg_total_relation_size(relid)) rows into a
-- tracking table (see automation/growth-monitoring/ for a ready-to-schedule
-- collector that creates and populates it) and computes growth between the
-- earliest and latest sample in the retention window.
--
-- This tracking table is optional infrastructure, not a built-in catalog --
-- on a database where the collector has never been deployed, the table
-- will not exist yet. to_regclass() is used (rather than a bare
-- `FROM dba_toolkit.table_size_history`, or a `::regclass` cast, both of
-- which fail at parse/analysis time with "relation does not exist" the
-- moment the statement is sent) so this script can detect that case and
-- print an instructional notice instead of hard-failing.
\\set tracking_table 'dba_toolkit.table_size_history'
\\set lookback_days 30
SELECT to_regclass(:'tracking_table') IS NOT NULL                AS tracking_table_exists
\\gset

\\if :tracking_table_exists
SELECT
    schema_name,
    table_name,
    min(size_bytes)  FILTER (WHERE captured_at = first_capture) AS start_size_bytes,
    max(size_bytes)  FILTER (WHERE captured_at = last_capture)  AS end_size_bytes,
    pg_size_pretty(
        (max(size_bytes) FILTER (WHERE captured_at = last_capture) -
         min(size_bytes) FILTER (WHERE captured_at = first_capture))::bigint
    )                                                            AS growth_over_window
FROM (
    SELECT
        schema_name,
        table_name,
        captured_at,
        size_bytes,
        min(captured_at) OVER (PARTITION BY schema_name, table_name) AS first_capture,
        max(captured_at) OVER (PARTITION BY schema_name, table_name) AS last_capture
    FROM dba_toolkit.table_size_history
    WHERE captured_at > now() - make_interval(days => :lookback_days)
) sized
GROUP BY schema_name, table_name
ORDER BY (max(size_bytes) - min(size_bytes)) DESC;
\\else
SELECT
    :'tracking_table' || ' does not exist in this database, so no growth-'
    'over-time history is available yet. Deploy the collector in '
    'automation/growth-monitoring/ (it creates this table and schedules a '
    'periodic INSERT of current relation sizes) and re-run this script '
    'after at least two collection intervals have elapsed. In the '
    'meantime, use storage-and-capacity/table-growth for a single-point-in-'
    'time size snapshot.'                                        AS notice;
\\endif
""".strip("\n")


def wal_activity() -> str:
    return """
-- Cluster-wide WAL generation statistics since the last stats reset
-- (pg_stat_wal, added in PostgreSQL 14 and unchanged in structure in 17).
-- Sustained high wal_bytes correlates directly with Aurora storage I/O and
-- with replica apply lag; compare two snapshots over a known time window to
-- get a WAL bytes/sec rate.
--
-- IMPORTANT (verified against Aurora PostgreSQL 17.7): pg_stat_wal is
-- present in the catalog on Aurora, but SELECTing it invokes the
-- underlying pg_stat_get_wal() function, which Aurora PostgreSQL does not
-- implement -- it raises "function pg_stat_get_wal() does not exist" even
-- though standard community PostgreSQL 17 supports it. Aurora does not
-- expose engine-internal WAL generation counters through this view at all
-- (WAL/redo generation happens against Aurora's distributed storage layer,
-- not local disk, so the community WAL-writer statistics this view
-- describes do not map onto Aurora's architecture). Detect Aurora *before*
-- ever sending a statement that references pg_stat_wal, so the
-- unsupported view/function is never parsed/resolved on the Aurora
-- execution path at all.
--
-- The detection below is a plain data-level check, never a call to an
-- Aurora-only function itself (so nothing here can fail on non-Aurora
-- PostgreSQL either): current_setting(name, missing_ok) is a stable core
-- PostgreSQL function that returns NULL instead of raising when the named
-- GUC does not exist, so it is safe to probe Aurora-only parameters with
-- it on any engine. Three independent Aurora signals are OR'd together so
-- a single naming/version quirk in one signal cannot cause a false
-- negative that would fall through to the unsupported pg_stat_wal branch:
--   1. the `aurora_version` GUC, which only exists on Aurora PostgreSQL
--      (visible via `SHOW aurora_version;` on a real Aurora instance);
--   2. the `rds.extensions` GUC, present on every RDS/Aurora PostgreSQL
--      instance (never on self-managed/community PostgreSQL);
--   3. the presence of the Aurora-specific aurora_version() SQL function
--      in pg_proc (checked by name only -- a catalog lookup, not a call).
SELECT (
    current_setting('aurora_version', true) IS NOT NULL
    OR current_setting('rds.extensions', true) IS NOT NULL
    OR EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'aurora_version')
)                                                                AS is_aurora
\\gset

\\if :is_aurora
SELECT
    'NOT AVAILABLE on Aurora PostgreSQL'::text                    AS status,
    'pg_stat_wal reports community PostgreSQL WAL-writer statistics that '
    'rely on pg_stat_get_wal(), which Aurora PostgreSQL (verified through '
    '17.7) does not implement -- querying pg_stat_wal here raises '
    '"function pg_stat_get_wal() does not exist". Aurora''s WAL/redo '
    'generation is written directly to the distributed storage layer, not '
    'local disk, so use the CloudWatch VolumeWriteIOPs / '
    'VolumeBytesUsed / WriteThroughput metrics, or the Performance '
    'Insights wait-event breakdown (wal_write / wal_sync / Log wait '
    'events), as the Aurora-native source for write/WAL volume instead.'
                                                                   AS guidance;
\\else
SELECT
    wal_records,
    wal_fpi,
    pg_size_pretty(wal_bytes)                                    AS total_wal_bytes,
    wal_buffers_full,
    wal_write,
    wal_sync,
    round(wal_write_time::numeric, 2)                             AS wal_write_time_ms,
    round(wal_sync_time::numeric, 2)                              AS wal_sync_time_ms,
    stats_reset
FROM pg_stat_wal;
\\endif
""".strip("\n")


def checkpoint_activity() -> str:
    return """
-- Checkpointer statistics. PostgreSQL 17 moved these counters out of
-- pg_stat_bgwriter into their own pg_stat_checkpointer view -- do not query
-- pg_stat_bgwriter for checkpoint counters on 17, they no longer exist
-- there. Frequent num_requested (forced) checkpoints relative to num_timed
-- (scheduled) checkpoints indicates checkpoint_timeout/max_wal_size are too
-- small for the current write rate.
SELECT
    num_timed,
    num_requested,
    round(
        100.0 * num_requested / NULLIF(num_timed + num_requested, 0), 2
    )                                                            AS pct_forced_checkpoints,
    buffers_written,
    round(write_time::numeric, 2)                                 AS write_time_ms,
    round(sync_time::numeric, 2)                                  AS sync_time_ms,
    stats_reset
FROM pg_stat_checkpointer;
""".strip("\n")


def bgwriter_activity() -> str:
    return """
-- Background writer activity (PG17 pg_stat_bgwriter is now limited to
-- non-checkpoint buffer writes: buffers_clean/maxwritten_clean/
-- buffers_alloc). Per-backend-type I/O detail, including buffers written
-- directly by backends under memory pressure, moved to pg_stat_io in
-- PostgreSQL 16+; query that view for the fuller I/O breakdown.
SELECT
    buffers_clean,
    maxwritten_clean,
    buffers_alloc,
    stats_reset
FROM pg_stat_bgwriter;
""".strip("\n")


def pg_stat_io_summary() -> str:
    return """
-- Per-backend-type I/O statistics (added PostgreSQL 16, still current in
-- 17). Useful to see whether I/O pressure is coming from regular client
-- backends, autovacuum workers, or background writer/checkpointer activity.
--
-- IMPORTANT (verified against Aurora PostgreSQL 17.7): pg_stat_io on
-- PostgreSQL 17 does NOT have read_bytes/write_bytes/extend_bytes columns
-- -- those were only added in PostgreSQL 18. On 17, every I/O operation is
-- the same fixed size, reported separately as `op_bytes` (typically 8192,
-- one buffer page), so the actual byte volume must be derived numerically
-- as reads * op_bytes / writes * op_bytes rather than read directly.
-- Referencing read_bytes/write_bytes directly on 17 raises
-- "column does not exist".
SELECT
    backend_type,
    object,
    context,
    reads,
    op_bytes,
    pg_size_pretty((reads * op_bytes)::numeric)                   AS read_bytes_derived,
    writes,
    pg_size_pretty((writes * op_bytes)::numeric)                  AS write_bytes_derived,
    extends,
    hits,
    round(read_time::numeric, 2)                                  AS read_time_ms,
    round(write_time::numeric, 2)                                 AS write_time_ms
FROM pg_stat_io
WHERE reads > 0 OR writes > 0 OR hits > 0
ORDER BY (reads * op_bytes) DESC NULLS LAST;
""".strip("\n")


def temp_file_usage_by_database() -> str:
    return """
-- Cumulative temp file counters per database. A rising temp_bytes rate
-- indicates queries are spilling sorts/hashes/materializations to disk,
-- most often because work_mem is undersized for the actual query shapes
-- running in production, or because statistics are stale and the planner
-- underestimates row counts.
SELECT
    datname,
    temp_files,
    pg_size_pretty(temp_bytes)                                    AS temp_bytes_total,
    stats_reset
FROM pg_stat_database
WHERE datname IS NOT NULL
ORDER BY temp_bytes DESC;
""".strip("\n")


# ---------------------------------------------------------------------------
# Replication / HA / Aurora
# ---------------------------------------------------------------------------

def cluster_recovery_role() -> str:
    return """
-- Is this instance currently a writer or a reader? On Aurora, every reader
-- instance is always in continuous recovery mode (pg_is_in_recovery() =
-- true), even though it is not a traditional PostgreSQL physical standby --
-- it is replaying redo log records shipped from the shared Aurora storage
-- layer, not a WAL stream from the writer. Always confirm this before
-- interpreting any other replication-related query on this connection.
SELECT
    pg_is_in_recovery()                                          AS is_reader_instance,
    CASE WHEN pg_is_in_recovery()
         THEN 'This connection is to an Aurora reader instance (or a standard PostgreSQL physical replica).'
         ELSE 'This connection is to the Aurora writer instance (or a standalone/primary PostgreSQL server).'
    END                                                           AS role_description;
""".strip("\n")


def standard_streaming_replication_status() -> str:
    return """
-- Standard PostgreSQL streaming replication status, as seen from the writer.
-- IMPORTANT (Aurora-specific): this view only shows genuine WAL-streaming
-- consumers -- e.g. a logical replication subscriber, an external physical
-- replica, or AWS DMS -- connected to this instance. It does NOT show
-- Aurora's own reader instances, because Aurora readers do not attach as
-- standard streaming replicas; they read redo records from the shared
-- Aurora storage volume through an internal mechanism that is invisible to
-- pg_stat_replication. Use aurora_replica_status() (writer or reader) or
-- the AWS Console/CloudWatch AuroraReplicaLag metric to observe Aurora
-- reader lag; never assume an empty pg_stat_replication result means "no
-- replicas" on Aurora.
SELECT
    pid,
    usename,
    application_name,
    client_addr,
    state,
    sync_state,
    write_lag,
    flush_lag,
    replay_lag
FROM pg_stat_replication
ORDER BY replay_lag DESC NULLS LAST;
""".strip("\n")


def aurora_replica_status() -> str:
    return """
-- Aurora-specific cluster-wide replica status and lag, callable from any
-- instance in the cluster (writer or reader). This is the correct,
-- Aurora-native way to check reader lag -- it reflects the actual Aurora
-- storage-layer replication mechanism, not standard PostgreSQL streaming
-- replication. The exact column set has evolved across Aurora PostgreSQL
-- engine releases, so this script selects all columns explicitly via
-- information_schema-free SELECT * (a documented, deliberate exception to
-- the "no bare SELECT *" rule, since the function's return type is
-- engine-version-defined rather than a fixed catalog): confirm the columns
-- returned in your environment with \\x and adjust downstream automation
-- accordingly.
SELECT *
FROM aurora_replica_status()
ORDER BY 1;
""".strip("\n")


def replication_slots_and_wal_retention() -> str:
    return """
-- Combines replication slot lag with current WAL position to flag slots
-- that are retaining an unusually large amount of WAL. On Aurora, WAL
-- retained by an inactive or lagging logical replication slot still
-- consumes storage on the cluster volume and can eventually force
-- corrective action (dropping the slot) if the consumer cannot be
-- recovered.
--
-- IMPORTANT (verified against Aurora PostgreSQL 17.7): pg_current_wal_lsn()
-- errors on Aurora clusters running with wal_level=replica (Aurora's
-- default) -- Aurora's current-WAL-position tracking for this family of
-- functions depends on the same logical-WAL-cache infrastructure used by
-- logical replication, and is only reliably callable once
-- wal_level=logical is set. current_setting('wal_level') is a plain GUC
-- read that never fails, so it is used here as a guard: a CASE expression
-- only evaluates the branch matching its WHEN condition (the same
-- documented mechanism used to avoid division-by-zero in a CASE), so
-- pg_current_wal_lsn() is never actually invoked unless wal_level is
-- already 'logical'. The current position is computed once in a CTE and
-- reused, so the guard only needs to be evaluated a single time per query.
\\set retained_wal_warning_gb 50
-- NOTE: the threshold is cast to numeric BEFORE multiplying by 1024^3.
-- pg_wal_lsn_diff() returns numeric, but the psql-substituted literal
-- ":retained_wal_warning_gb" is a bare integer constant; PostgreSQL infers
-- an int4 literal type for "50 * 1024 * 1024 * 1024" left-to-right before
-- ever comparing it against the numeric LSN diff, and that intermediate
-- product (~53.7 billion) overflows int4 (max ~2.1 billion), raising
-- "integer out of range" -- casting the threshold to numeric first forces
-- numeric arithmetic throughout and avoids the overflow entirely.
WITH current_position AS (
    SELECT CASE WHEN current_setting('wal_level') = 'logical'
                THEN pg_current_wal_lsn()
                ELSE NULL
           END AS lsn
)
SELECT
    s.slot_name,
    s.slot_type,
    s.active,
    s.wal_status,
    CASE WHEN c.lsn IS NOT NULL
         THEN pg_size_pretty(pg_wal_lsn_diff(c.lsn, s.restart_lsn))
         ELSE 'NOT AVAILABLE (wal_level=' || current_setting('wal_level') || ', requires logical on Aurora)'
    END                                                             AS retained_wal,
    CASE WHEN c.lsn IS NOT NULL
         THEN pg_wal_lsn_diff(c.lsn, s.restart_lsn) >
              (:retained_wal_warning_gb::numeric * 1024 * 1024 * 1024)
         ELSE NULL
    END                                                             AS exceeds_warning_threshold
FROM pg_replication_slots s
CROSS JOIN current_position c
ORDER BY (CASE WHEN c.lsn IS NOT NULL THEN pg_wal_lsn_diff(c.lsn, s.restart_lsn) ELSE NULL END) DESC NULLS LAST;
""".strip("\n")


# ---------------------------------------------------------------------------
# Settings / environment / prerequisites
# ---------------------------------------------------------------------------

def key_settings_snapshot() -> str:
    return """
-- Snapshot of the settings that most commonly explain performance and
-- concurrency behavior differences between environments. On Aurora, most of
-- these are controlled by the DB cluster parameter group (values shared by
-- all instances) or the DB instance parameter group (writer/reader-specific
-- overrides), not postgresql.conf -- use the AWS Console/CLI
-- (describe-db-cluster-parameters / describe-db-parameters) to change them,
-- not ALTER SYSTEM, which Aurora does not support for most parameters.
SELECT
    name,
    setting,
    unit,
    category,
    short_desc,
    context
FROM pg_settings
WHERE name IN (
    'max_connections', 'shared_buffers', 'work_mem', 'maintenance_work_mem',
    'effective_cache_size', 'autovacuum', 'autovacuum_max_workers',
    'autovacuum_naptime', 'autovacuum_vacuum_cost_limit',
    'autovacuum_freeze_max_age', 'autovacuum_multixact_freeze_max_age',
    'checkpoint_timeout', 'max_wal_size', 'statement_timeout',
    'idle_in_transaction_session_timeout', 'lock_timeout',
    'log_lock_waits', 'deadlock_timeout', 'track_io_timing',
    'shared_preload_libraries', 'random_page_cost', 'effective_io_concurrency'
)
ORDER BY name;
""".strip("\n")


def extension_inventory() -> str:
    return """
-- Extensions currently installed in this database vs. what Aurora
-- PostgreSQL makes available. Many investigation scripts in this toolkit
-- depend on pg_stat_statements (query stats) and/or pgstattuple (exact
-- bloat); confirm both are available/installed before relying on those
-- scripts.
SELECT
    e.extname,
    e.extversion,
    n.nspname                                                   AS installed_schema
FROM pg_extension e
JOIN pg_namespace n ON n.oid = e.extnamespace
ORDER BY e.extname;
""".strip("\n")


def available_extensions_check() -> str:
    return """
-- Confirms whether a specific extension is available to install on this
-- Aurora PostgreSQL instance (it may be available but not yet CREATE
-- EXTENSION'd). Aurora PostgreSQL supports a curated allowlist of
-- extensions per engine version; if an extension you need is missing from
-- pg_available_extensions entirely (not just pg_extension), it is not
-- supported on this Aurora engine version and must be requested via AWS
-- support or worked around at the application layer.
\\set extension_name 'pg_stat_statements'
SELECT
    name,
    default_version,
    installed_version,
    comment
FROM pg_available_extensions
WHERE name = :'extension_name';
""".strip("\n")


def current_role_privileges() -> str:
    return """
-- What the currently connected role can actually do: superuser-equivalent
-- Aurora role membership, and the built-in monitoring roles that grant
-- read access to statistics views without needing broader privileges. On
-- Aurora/RDS, the true "superuser" is reserved for AWS-managed processes;
-- the bootstrap application user is typically only a member of
-- rds_superuser, which is intentionally weaker (no filesystem/OS access).
SELECT
    r.rolname,
    r.rolsuper,
    r.rolcreaterole,
    r.rolcreatedb,
    r.rolreplication,
    r.rolbypassrls,
    ARRAY(
        SELECT b.rolname
        FROM pg_auth_members m
        JOIN pg_roles b ON b.oid = m.roleid
        WHERE m.member = r.oid
    )                                                            AS member_of_roles
FROM pg_roles r
WHERE r.rolname = current_user;
""".strip("\n")


# ---------------------------------------------------------------------------
# Storage breakdown / capacity planning (appended for storage-and-capacity)
# ---------------------------------------------------------------------------

def schema_sizes() -> str:
    return """
-- On-disk footprint of every user schema in the current database (heap +
-- indexes + TOAST for every relation the schema owns). On a crypto-exchange
-- schema layout this is the fastest way to attribute growth to a business
-- domain: the trading path (orders, trades, order_book_snapshots), the
-- money path (wallets, ledger_entries, deposits, withdrawals), or an
-- audit/compliance schema nobody has ever pruned.
--
-- Partitioned parents (relkind 'p') have no storage of their own; their
-- partitions are separate 'r' relations and are counted individually, so
-- there is no double counting here.
SELECT
    n.nspname                                                    AS schema_name,
    count(*)                                                     AS relation_count,
    pg_size_pretty(sum(pg_total_relation_size(c.oid)))            AS total_size,
    sum(pg_total_relation_size(c.oid))                            AS total_size_bytes,
    round(
        100.0 * sum(pg_total_relation_size(c.oid)) / NULLIF((
            SELECT sum(pg_total_relation_size(c2.oid))
            FROM pg_class c2
            JOIN pg_namespace n2 ON n2.oid = c2.relnamespace
            WHERE c2.relkind IN ('r', 'p', 'm')
              AND n2.nspname NOT IN ('pg_catalog', 'information_schema')
        ), 0), 2
    )                                                            AS pct_of_user_data
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p', 'm')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
GROUP BY n.nspname
ORDER BY sum(pg_total_relation_size(c.oid)) DESC;
""".strip("\n")


def object_counts_by_schema() -> str:
    return """
-- Object counts per user schema, broken down by relation kind. Storage
-- growth is not always about row volume: a partitioned ledger table whose
-- maintenance job creates daily partitions but never detaches old ones
-- accumulates thousands of child relations and index entries, which inflates
-- the system catalogs themselves, slows planning, and increases the
-- per-relation lock footprint of every DDL statement touching the parent.
SELECT
    n.nspname                                                    AS schema_name,
    count(*) FILTER (WHERE c.relkind = 'r')                       AS ordinary_tables,
    count(*) FILTER (WHERE c.relkind = 'p')                       AS partitioned_parents,
    count(*) FILTER (WHERE c.relkind = 'i')                       AS indexes,
    count(*) FILTER (WHERE c.relkind = 'I')                       AS partitioned_indexes,
    count(*) FILTER (WHERE c.relkind = 'm')                       AS materialized_views,
    count(*) FILTER (WHERE c.relkind = 'v')                       AS views,
    count(*) FILTER (WHERE c.relkind = 'S')                       AS sequences,
    count(*)                                                     AS total_objects
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
GROUP BY n.nspname
ORDER BY count(*) DESC;
""".strip("\n")


def table_size_components() -> str:
    return """
-- Splits each large relation's footprint into its three physical
-- components -- main heap fork, TOAST (out-of-line storage for wide values
-- such as JSON order payloads, raw blockchain transaction bodies, or
-- serialized order-book snapshots), and indexes -- so growth can be
-- attributed to the right cause before any remediation is chosen.
--
-- pg_relation_size(oid) returns the main fork only; pg_indexes_size(oid)
-- sums every index on the relation; the TOAST branch is guarded with a
-- reltoastrelid <> 0 test because relations with no varlena columns have
-- no TOAST relation at all.
\\set top_n 30
SELECT
    n.nspname                                                    AS schema_name,
    c.relname                                                    AS table_name,
    pg_size_pretty(pg_relation_size(c.oid))                       AS heap_main_fork,
    pg_size_pretty(
        CASE WHEN c.reltoastrelid <> 0
             THEN pg_total_relation_size(c.reltoastrelid)
             ELSE 0 END
    )                                                            AS toast_total,
    pg_size_pretty(pg_indexes_size(c.oid))                        AS index_total,
    pg_size_pretty(pg_total_relation_size(c.oid))                 AS grand_total,
    round(
        100.0 * pg_indexes_size(c.oid)
        / NULLIF(pg_total_relation_size(c.oid), 0), 1
    )                                                            AS pct_indexes,
    round(
        100.0 * (CASE WHEN c.reltoastrelid <> 0
                      THEN pg_total_relation_size(c.reltoastrelid)
                      ELSE 0 END)
        / NULLIF(pg_total_relation_size(c.oid), 0), 1
    )                                                            AS pct_toast,
    c.reltuples::bigint                                          AS estimated_row_count
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p', 'm')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY pg_total_relation_size(c.oid) DESC
LIMIT :top_n;
""".strip("\n")


def write_volume_by_table() -> str:
    return """
-- Row-level write volume per table since the last statistics reset. This is
-- the single best in-database proxy for "which tables are actually driving
-- storage and WAL growth", because every insert, every non-HOT update
-- (which writes a whole new row version plus every index entry), and every
-- delete (which leaves a dead tuple until vacuum reclaims it) contributes
-- directly to both.
--
-- Counters are cumulative since the last reset; pg_stat_all_tables has no
-- stats_reset column of its own, so read stats_reset from pg_stat_database
-- for the current database to know what window these numbers cover.
\\set top_n 30
SELECT
    schemaname                                                  AS schema_name,
    relname                                                     AS table_name,
    n_tup_ins,
    n_tup_upd,
    n_tup_del,
    n_tup_hot_upd,
    n_tup_ins + n_tup_upd + n_tup_del                            AS total_row_writes,
    round(100.0 * n_tup_hot_upd / NULLIF(n_tup_upd, 0), 1)        AS pct_hot_updates,
    n_live_tup,
    n_dead_tup,
    pg_size_pretty(pg_total_relation_size(relid))                 AS total_size,
    (SELECT stats_reset FROM pg_stat_database
      WHERE datname = current_database())                        AS stats_reset
FROM pg_stat_all_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY (n_tup_ins + n_tup_upd + n_tup_del) DESC
LIMIT :top_n;
""".strip("\n")


def index_to_table_size_ratio() -> str:
    return """
-- Tables whose index footprint is large relative to their heap. A ratio
-- above roughly 1.0 (more bytes in indexes than in the table itself) is
-- normal for a narrow, heavily queried lookup table but is a strong
-- over-indexing signal on a wide, write-heavy table such as an order or
-- ledger table -- every extra index multiplies write amplification, WAL
-- volume, and vacuum cost, not just stored bytes.
\\set top_n 30
\\set min_total_bytes 104857600
SELECT
    n.nspname                                                    AS schema_name,
    c.relname                                                    AS table_name,
    count(ix.indexrelid)                                         AS index_count,
    pg_size_pretty(pg_relation_size(c.oid))                       AS heap_size,
    pg_size_pretty(pg_indexes_size(c.oid))                        AS index_size,
    round(
        pg_indexes_size(c.oid)::numeric
        / NULLIF(pg_relation_size(c.oid), 0), 2
    )                                                            AS index_to_heap_ratio,
    pg_size_pretty(pg_total_relation_size(c.oid))                 AS total_size
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_index ix ON ix.indrelid = c.oid
WHERE c.relkind IN ('r', 'p')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND pg_total_relation_size(c.oid) >= :min_total_bytes
GROUP BY n.nspname, c.relname, c.oid
ORDER BY (pg_indexes_size(c.oid)::numeric / NULLIF(pg_relation_size(c.oid), 0))
         DESC NULLS LAST
LIMIT :top_n;
""".strip("\n")


# ---------------------------------------------------------------------------
# Schema-change / DDL pre-flight and progress (appended for schema-changes)
# ---------------------------------------------------------------------------

def create_index_progress() -> str:
    return """
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
""".strip("\n")


def ddl_safety_settings() -> str:
    return """
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
""".strip("\n")


def index_and_constraint_inventory_for_table() -> str:
    return """
-- Complete index and constraint inventory for one target table, which is
-- the mandatory pre-flight read before any schema change: it tells you what
-- already exists (so you do not build a redundant index), which indexes back
-- constraints (so you do not attempt to drop one directly), and whether any
-- index is currently INVALID or NOT READY from an earlier failed build.
--
-- Ships with an illustrative default (public.trades) -- edit the \\set lines
-- below for your real target. Both branches compare the name only inside a
-- catalog WHERE clause and never cast it to regclass, so this script is
-- safe to run unmodified even when that table does not exist here: it simply
-- returns zero rows.
\\set schema_name 'public'
\\set table_name 'trades'
SELECT
    'index'                                                     AS object_type,
    i.relname                                                    AS object_name,
    pg_size_pretty(pg_relation_size(i.oid))                       AS object_size,
    ix.indisvalid                                                AS is_valid,
    ix.indisready                                                AS is_ready,
    ix.indisprimary                                              AS is_primary,
    ix.indisunique                                               AS is_unique,
    pg_get_indexdef(ix.indexrelid)                               AS definition
FROM pg_index ix
JOIN pg_class c ON c.oid = ix.indrelid
JOIN pg_class i ON i.oid = ix.indexrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = :'schema_name'
  AND c.relname = :'table_name'
UNION ALL
SELECT
    'constraint',
    con.conname,
    NULL,
    con.convalidated,
    NULL,
    con.contype = 'p',
    con.contype IN ('u', 'p'),
    pg_get_constraintdef(con.oid)
FROM pg_constraint con
JOIN pg_class c ON c.oid = con.conrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = :'schema_name'
  AND c.relname = :'table_name'
ORDER BY object_type, object_name;
""".strip("\n")


def target_table_size_detail() -> str:
    return """
-- Size, row estimate, and maintenance state for a single target table --
-- the numbers that determine how long a rewriting DDL statement will hold
-- its lock, and therefore whether the operation can be done directly or
-- needs the online (build-alongside-and-swap) pattern instead.
--
-- Ships with an illustrative default (public.trades); edit the \\set lines
-- below for your real target. to_regclass() is used throughout rather than
-- a ::regclass cast, because a cast raises "relation does not exist" and
-- aborts the statement outright when the name is absent, whereas
-- to_regclass() simply returns NULL and lets the guard print guidance.
\\set schema_name 'public'
\\set table_name 'trades'
SELECT to_regclass(:'schema_name' || '.' || :'table_name') IS NOT NULL
                                                             AS target_table_exists
\\gset

\\if :target_table_exists
SELECT
    :'schema_name' || '.' || :'table_name'                        AS target_table,
    pg_size_pretty(pg_relation_size(
        to_regclass(:'schema_name' || '.' || :'table_name')))     AS heap_size,
    pg_size_pretty(pg_indexes_size(
        to_regclass(:'schema_name' || '.' || :'table_name')))     AS index_size,
    pg_size_pretty(pg_total_relation_size(
        to_regclass(:'schema_name' || '.' || :'table_name')))     AS total_size,
    pg_total_relation_size(
        to_regclass(:'schema_name' || '.' || :'table_name'))      AS total_size_bytes,
    s.n_live_tup,
    s.n_dead_tup,
    s.n_mod_since_analyze,
    s.last_vacuum,
    s.last_autovacuum,
    s.last_analyze,
    s.last_autoanalyze,
    (SELECT count(*) FROM pg_index ix
      WHERE ix.indrelid = to_regclass(:'schema_name' || '.' || :'table_name'))
                                                                 AS index_count
FROM pg_stat_all_tables s
WHERE s.relid = to_regclass(:'schema_name' || '.' || :'table_name');
\\else
SELECT
    'Table ' || :'schema_name' || '.' || :'table_name' || ' does not exist '
    'in this database. Edit the schema_name/table_name \\set lines at the top '
    'of this script to point at the real table you intend to change, then '
    're-run. Realistic targets on an exchange platform include public.orders, '
    'public.trades, public.ledger_entries, public.wallets, public.deposits '
    'and public.withdrawals.'                                     AS notice;
\\endif
""".strip("\n")
