/*
===============================================================================
SCRIPT NAME:
01_current_wait_event_snapshot.sql

PURPOSE:
Aggregates current backends by wait event, the same taxonomy Performance Insights uses to color its DB load chart.

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
Step 01 of workflow 'observability/performance-insights'

RELATED SCRIPTS:
02_active_session_load_by_query.sql, ../wait-event-analysis/README.md

HOW TO INTERPRET RESULTS:
Use this to sanity-check what PI's console is showing right now, or as the fallback when PI is not yet enabled on this instance. A concentration of backends in a single wait_event_type mirrors exactly what a spike in PI's stacked chart at this moment would show.
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
