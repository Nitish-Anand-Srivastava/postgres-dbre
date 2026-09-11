/*
===============================================================================
SCRIPT NAME:
01_current_wait_event_summary.sql

PURPOSE:
Aggregates current backends by wait event type/name, joined to pg_wait_events for a plain-language description.

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
Step 01 of workflow 'observability/wait-event-analysis'

RELATED SCRIPTS:
02_wait_event_contention_by_type_and_state.sql

HOW TO INTERPRET RESULTS:
Read this as the overall shape of current load before drilling into anything specific. A healthy exchange writer under normal load shows mostly Client/Activity (expected idle) with a small amount of CPU-bound activity; any large concentration in Lock, IO, or IPC is the signal to drill into script 02 or 03 immediately.
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
