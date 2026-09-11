/*
===============================================================================
SCRIPT NAME:
04_check_wait_events.sql

PURPOSE:
Aggregates current wait events to confirm whether load is genuinely CPU-bound vs. lock/IO-bound.

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
Step 04 of workflow 'performance/high-cpu'

RELATED SCRIPTS:
05_check_lock_contention.sql

HOW TO INTERPRET RESULTS:
A high proportion of NULL wait_event on active sessions confirms CPU-bound work. A high proportion of Lock/IO wait events means the real bottleneck is elsewhere -- pivot to concurrency-and-locking or storage-and-capacity workflows.
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
