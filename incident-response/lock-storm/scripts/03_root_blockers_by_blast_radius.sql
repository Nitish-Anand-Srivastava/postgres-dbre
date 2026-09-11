/*
===============================================================================
SCRIPT NAME:
03_root_blockers_by_blast_radius.sql

PURPOSE:
Collapses the wait graph to the handful of blockers that matter, and identifies which of them are true roots.

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
Step 03 of workflow 'incident-response/lock-storm'

RELATED SCRIPTS:
04_lock_detail_at_the_root.sql

HOW TO INTERPRET RESULTS:
Act only on rows where blocker_is_itself_blocked_by_count = 0: those are true roots. Among them, prefer the one with the largest directly_blocked_sessions, and prefer a blocker whose state is 'idle in transaction' -- it is holding everyone up while doing no work at all.
===============================================================================
*/

-- Root-cause ranking for a lock storm: every backend that is blocking at
-- least one other backend, ranked by how many sessions it is directly
-- blocking. During a storm the raw pg_locks output is overwhelming -- this
-- collapses it to the handful of pids that actually matter.
--
-- Read blocker_is_itself_blocked_by_count first: a value of 0 means this
-- backend is a TRUE ROOT of the wait graph (nothing is blocking it, so it
-- will never clear by waiting for somebody else). A non-zero value means it
-- is a middle link in the chain, and resolving it achieves nothing because
-- the real root is further up.
SELECT
    b.blocking_pid,
    a.usename                                                   AS blocker_user,
    coalesce(NULLIF(a.application_name, ''), '(unset)')          AS blocker_application,
    a.datname                                                    AS blocker_database,
    a.state                                                      AS blocker_state,
    a.wait_event_type                                            AS blocker_wait_event_type,
    a.wait_event                                                 AS blocker_wait_event,
    now() - a.xact_start                                         AS blocker_txn_age,
    now() - a.state_change                                       AS blocker_time_in_state,
    count(*)                                                     AS directly_blocked_sessions,
    cardinality(pg_blocking_pids(b.blocking_pid))                AS blocker_is_itself_blocked_by_count,
    left(a.query, 200)                                           AS blocker_query
FROM (
    SELECT unnest(pg_blocking_pids(w.pid))                       AS blocking_pid
    FROM pg_stat_activity w
    WHERE cardinality(pg_blocking_pids(w.pid)) > 0
) b
JOIN pg_stat_activity a ON a.pid = b.blocking_pid
GROUP BY b.blocking_pid, a.usename, a.application_name, a.datname, a.state,
         a.wait_event_type, a.wait_event, a.xact_start, a.state_change, a.query
ORDER BY directly_blocked_sessions DESC, blocker_txn_age DESC NULLS LAST;
