/*
===============================================================================
SCRIPT NAME:
02_cpu_versus_wait_breakdown.sql

PURPOSE:
Separates genuine CPU-bound work from sessions that are merely waiting -- the check that decides whether this is really a CPU incident.

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
Step 02 of workflow 'incident-response/high-cpu'

RELATED SCRIPTS:
03_top_active_queries_now.sql

HOW TO INTERPRET RESULTS:
Active sessions with no wait event are the real CPU consumers. If most sessions are waiting on Lock or IO, the CPU alarm is a side effect and you should be in the lock-storm or latency workflow instead -- confirm this before doing anything else, because it inverts the entire response.
===============================================================================
*/

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
