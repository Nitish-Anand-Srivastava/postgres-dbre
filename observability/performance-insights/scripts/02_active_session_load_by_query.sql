/*
===============================================================================
SCRIPT NAME:
02_active_session_load_by_query.sql

PURPOSE:
Groups currently active sessions by query_id and wait event, approximating PI's Top SQL / DB load by SQL breakdown from live catalog data.

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
Step 02 of workflow 'observability/performance-insights'

RELATED SCRIPTS:
03_enabling_and_interpreting_performance_insights.md

HOW TO INTERPRET RESULTS:
active_session_count per query_id is this instant's contribution to DB load from that statement -- the same concept as PI's AAS-by-SQL ranking, just computed live instead of from PI's continuous sampling. Take query_id to pg_stat_statements (slow-query-observability) for the statement's full cumulative execution statistics rather than relying on the truncated sample_query_text here.
===============================================================================
*/

-- Approximates Performance Insights' "DB load by SQL" breakdown using only
-- native catalog data -- useful when PI is not yet enabled, or when
-- cross-referencing a queryid PI surfaced against the exact live query text.
-- PostgreSQL 14+ (unchanged through 17) exposes query_id directly on
-- pg_stat_activity once compute_query_id is active, which pg_stat_statements
-- already requires internally -- so on any instance running
-- pg_stat_statements this is populated with no extra configuration.
SELECT
    a.query_id,
    a.wait_event_type,
    a.wait_event,
    count(*)                                                    AS active_session_count,
    array_agg(DISTINCT a.datname)                               AS databases,
    left(max(a.query), 200)                                     AS sample_query_text
FROM pg_stat_activity a
WHERE a.pid <> pg_backend_pid()
  AND a.state = 'active'
GROUP BY a.query_id, a.wait_event_type, a.wait_event
ORDER BY active_session_count DESC;
