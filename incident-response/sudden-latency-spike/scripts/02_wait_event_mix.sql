/*
===============================================================================
SCRIPT NAME:
02_wait_event_mix.sql

PURPOSE:
Reads the current wait-event distribution -- the fastest branch point for deciding which cause to pursue.

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
Step 02 of workflow 'incident-response/sudden-latency-spike'

RELATED SCRIPTS:
03_longest_active_queries.sql, ../lock-storm/README.md

HOW TO INTERPRET RESULTS:
Lock-dominated means go to lock-storm. IO-dominated means resource or checkpoint pressure (script 05). LWLock or IPC means internal contention from too much concurrency. An empty or tiny wait-event set with many active sessions means genuinely CPU-bound work, so use the high-cpu checklist in this category.
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
