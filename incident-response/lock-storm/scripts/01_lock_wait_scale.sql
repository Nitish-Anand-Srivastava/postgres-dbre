/*
===============================================================================
SCRIPT NAME:
01_lock_wait_scale.sql

PURPOSE:
Sizes the storm: how many backends are waiting, on what, and for how long.

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
Step 01 of workflow 'incident-response/lock-storm'

RELATED SCRIPTS:
02_blocked_sessions.sql

HOW TO INTERPRET RESULTS:
A large backend_count for wait_event_type = 'Lock' relative to total sessions confirms a lock storm rather than general slowness. If the dominant waits are IO or Client instead, you are in the wrong workflow -- go back to the latency or connection triage.
===============================================================================
*/

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
