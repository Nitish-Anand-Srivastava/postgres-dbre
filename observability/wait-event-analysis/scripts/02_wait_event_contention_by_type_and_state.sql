/*
===============================================================================
SCRIPT NAME:
02_wait_event_contention_by_type_and_state.sql

PURPOSE:
Breaks wait events down further by session state, to separate genuine contention from expected idle waiting.

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
Step 02 of workflow 'observability/wait-event-analysis'

RELATED SCRIPTS:
03_per_session_wait_event_detail.sql

HOW TO INTERPRET RESULTS:
Cross-tabulating by state distinguishes 'many sessions waiting on Client because they are idle between requests' (normal) from 'many active sessions waiting on Lock' (a genuine contention finding). longest_time_in_state flags the single longest-waiting session in each group, which is usually the most useful starting point for the per-session drill-down in script 03.
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
