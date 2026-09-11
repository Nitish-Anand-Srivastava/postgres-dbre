/*
===============================================================================
SCRIPT NAME:
01_pre_window_activity_and_transactions.sql

PURPOSE:
Pre-window snapshot of overall activity and of any transaction long-running enough to be destroyed mid-flight by the maintenance action.

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
Step 01 of workflow 'maintenance/planned-maintenance-window-checklist'

RELATED SCRIPTS:
02_pre_window_lock_and_blocking_check.sql

HOW TO INTERPRET RESULTS:
Run this immediately before the window, not hours earlier. Any transaction open longer than the planned window duration will be terminated by a reboot or failover -- identify what owns it (an end-of-day reconciliation, an archival batch, a reporting job) and either let it finish or coordinate its cancellation deliberately. An activity profile far above the expected off-peak baseline is itself a reason to reconsider the timing: maintenance during unexpectedly heavy order flow amplifies every consequence of the interruption.
===============================================================================
*/

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
