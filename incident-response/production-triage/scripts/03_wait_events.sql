/*
===============================================================================
SCRIPT NAME:
03_wait_events.sql

PURPOSE:
Step 3 of 10: the wait-event distribution across all backends -- the highest-signal single result in the checklist.

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
Step 03 of workflow 'incident-response/production-triage'

RELATED SCRIPTS:
04_blocking_locks.sql

HOW TO INTERPRET RESULTS:
Lock-dominated means blocking, and script 04 will confirm it. IO-dominated means resource or storage pressure. LWLock or IPC means internal contention from more concurrency than the instance can absorb. Few waits alongside many active sessions means genuine CPU-bound work. The PG17 pg_wait_events join means unfamiliar event names explain themselves without opening the manual.
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
