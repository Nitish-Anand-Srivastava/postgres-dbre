/*
===============================================================================
SCRIPT NAME:
03_sessions_spilling_now.sql

PURPOSE:
Catches sessions currently performing temporary file I/O, using the BufFile wait events.

AURORA POSTGRESQL VERSION:
Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise)

EXECUTION LOCATION:
Writer instance preferred; safe to run on a reader but results reflect only that reader's local activity

SAFETY:
READ ONLY

EXPECTED IMPACT:
Minimal -- reads system catalogs/statistics views only, no table locks beyond a brief catalog lookup.

REQUIRED PRIVILEGES:
Role membership in `pg_monitor` (or `pg_read_all_stats`) is sufficient. No superuser required.

PREREQUISITES:
None beyond CONNECT on the target database.

EXECUTION ORDER:
Step 03 of workflow 'query-optimization/temp-file-investigation'

RELATED SCRIPTS:
04_memory_and_logging_settings.sql

HOW TO INTERPRET RESULTS:
A backend on BufFileRead or BufFileWrite is actively spilling right now, and its query snippet identifies the statement directly -- this is the fastest attribution path when a spill is happening while you watch. Sample it several times over a minute: a single empty result does not mean nothing is spilling, only that nothing was spilling at that instant. If many backends appear here simultaneously, the instance's local storage I/O is saturated by temporary files and unrelated queries are being slowed by it.
===============================================================================
*/

-- Backends that are, at this instant, reading or writing temporary files
-- (the BufFile* wait events) or otherwise waiting on I/O. Spills are often
-- brief, so run this repeatedly during the problem window rather than once
-- -- each execution is a sample, not a continuous trace.
--
-- pg_wait_events (PostgreSQL 17) is joined so every wait_event value
-- carries its canonical description without needing the manual.
SELECT
    a.pid,
    a.datname,
    a.usename,
    coalesce(NULLIF(a.application_name, ''), '(unset)')           AS application_name,
    a.client_addr,
    a.state,
    a.backend_type,
    a.wait_event_type,
    a.wait_event,
    we.description                                                AS wait_event_description,
    now() - a.query_start                                         AS query_runtime,
    now() - a.xact_start                                          AS txn_runtime,
    left(a.query, 200)                                            AS query_snippet
FROM pg_stat_activity a
LEFT JOIN pg_wait_events we
       ON we.type = a.wait_event_type
      AND we.name = a.wait_event
WHERE a.pid <> pg_backend_pid()
  AND (
        a.wait_event LIKE 'BufFile%'
     OR a.wait_event_type = 'IO'
      )
ORDER BY query_runtime DESC NULLS LAST;

-- Broader context: what every backend is waiting on right now, so the
-- temporary-file I/O above can be weighed against everything else
-- happening on this instance.
SELECT
    a.wait_event_type,
    a.wait_event,
    count(*)                                                      AS backend_count
FROM pg_stat_activity a
WHERE a.pid <> pg_backend_pid()
  AND a.wait_event IS NOT NULL
GROUP BY a.wait_event_type, a.wait_event
ORDER BY backend_count DESC;
