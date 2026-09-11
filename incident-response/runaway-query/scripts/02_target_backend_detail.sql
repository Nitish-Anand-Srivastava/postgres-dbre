/*
===============================================================================
SCRIPT NAME:
02_target_backend_detail.sql

PURPOSE:
Captures complete forensic detail for the specific backend, including its full query text and how many sessions it is blocking.

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
Step 02 of workflow 'incident-response/runaway-query'

RELATED SCRIPTS:
01_runaway_candidates.sql, 03_collateral_damage.sql

HOW TO INTERPRET RESULTS:
Set :target_pid to the pid from script 01 first; unedited, this script matches nothing and returns zero rows by design. Copy full_query_text into the incident channel before doing anything else -- it disappears the moment the backend ends. sessions_this_backend_blocks above zero means this is also a blocking incident.
===============================================================================
*/

-- Full forensic detail for ONE specific backend, identified in the previous
-- script. Set :target_pid to the pid under investigation before running.
--
-- The default of 0 is never a real backend pid, so an unedited run returns
-- zero rows rather than reporting on the wrong session -- this script is
-- deliberately safe to run exactly as shipped.
\set target_pid 0
SELECT
    a.pid,
    a.datname,
    a.usename,
    coalesce(NULLIF(a.application_name, ''), '(unset)')          AS application_name,
    a.client_addr,
    a.backend_type,
    a.backend_start,
    a.xact_start,
    a.query_start,
    a.state_change,
    a.state,
    a.wait_event_type,
    a.wait_event,
    a.backend_xid,
    a.backend_xmin,
    now() - a.query_start                                        AS query_runtime,
    now() - a.xact_start                                         AS txn_runtime,
    cardinality(pg_blocking_pids(a.pid))                         AS is_blocked_by_count,
    pg_blocking_pids(a.pid)                                      AS is_blocked_by_pids,
    (
        SELECT count(*)
        FROM pg_stat_activity w
        WHERE a.pid = ANY (pg_blocking_pids(w.pid))
    )                                                            AS sessions_this_backend_blocks,
    a.query                                                      AS full_query_text
FROM pg_stat_activity a
WHERE a.pid = :target_pid;
