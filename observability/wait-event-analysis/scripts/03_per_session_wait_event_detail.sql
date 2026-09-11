/*
===============================================================================
SCRIPT NAME:
03_per_session_wait_event_detail.sql

PURPOSE:
Row-per-session detail for every backend currently registering a wait event, with plain-language description and query text.

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
Step 03 of workflow 'observability/wait-event-analysis'

RELATED SCRIPTS:
04_wait_event_type_reference.md, ../../concurrency-and-locking/blocked-queries/README.md

HOW TO INTERPRET RESULTS:
The sessions with the longest time_in_current_wait are the ones to focus on first. For a Lock wait_event_type, cross-reference these pids against concurrency-and-locking/blocked-queries' blocking-session detail to find who is actually holding the lock this session is waiting for -- this view shows the waiter, not the blocker.
===============================================================================
*/

-- Row-per-session detail for every backend currently registering a wait
-- event, joined to pg_wait_events for a plain-language description. Use
-- this once the aggregated counts in scripts 01/02 show a wait_event_type
-- worth investigating and the exact responsible sessions/queries are
-- needed.
SELECT
    a.pid,
    a.usename,
    a.datname,
    a.wait_event_type,
    a.wait_event,
    we.description,
    a.state,
    now() - a.state_change                                        AS time_in_current_wait,
    left(a.query, 160)                                             AS query_snippet
FROM pg_stat_activity a
LEFT JOIN pg_wait_events we
       ON we.type = a.wait_event_type
      AND we.name = a.wait_event
WHERE a.pid <> pg_backend_pid()
  AND a.wait_event IS NOT NULL
ORDER BY time_in_current_wait DESC NULLS LAST;
