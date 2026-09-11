/*
===============================================================================
SCRIPT NAME:
02_active_sessions.sql

PURPOSE:
Step 2 of 10: sizes the incident with a session and state overview across the whole instance.

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
Step 02 of workflow 'incident-response/production-triage'

RELATED SCRIPTS:
03_wait_events.sql

HOW TO INTERPRET RESULTS:
Compare the active count against the instance's vCPU count and against your normal baseline for this time of day. Many active sessions means work is queueing; a large idle-in-transaction population means an application is leaking transactions; a completely normal profile despite a live report is itself a finding worth stating out loud.
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
