/*
===============================================================================
SCRIPT NAME:
01_client_and_ipc_wait_breakdown.sql

PURPOSE:
Breaks down current wait events specifically for Client and IPC types to isolate connection-level (as opposed to lock/IO) contention.

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
Step 01 of workflow 'concurrency-and-locking/connection-contention'

RELATED SCRIPTS:
02_connection_headroom.sql

HOW TO INTERPRET RESULTS:
A large ClientRead count on sessions inside an open transaction (cross-check against idle-in-transaction) suggests the client, not the database, is the bottleneck.
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
