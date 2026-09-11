/*
===============================================================================
SCRIPT NAME:
03_planning_vs_execution_time.sql

PURPOSE:
Separates time spent planning from time spent executing, to detect planning-bound statements.

AURORA POSTGRESQL VERSION:
Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise)

EXECUTION LOCATION:
Any instance (writer or reader)

SAFETY:
READ ONLY

EXPECTED IMPACT:
Minimal -- reads system catalogs/statistics views only, no table locks beyond a brief catalog lookup.

REQUIRED PRIVILEGES:
Role membership in `pg_monitor`, plus SELECT on `pg_stat_statements` (granted automatically to `pg_read_all_stats` once the extension is created; otherwise `GRANT SELECT ON pg_stat_statements TO <role>;`).

PREREQUISITES:
pg_stat_statements must be listed in shared_preload_libraries (an Aurora DB cluster parameter-group change that requires a reboot) and created in the current database. This script detects its absence and prints an instructional notice instead of failing, so it is safe to run either way.

EXECUTION ORDER:
Step 03 of workflow 'query-optimization/analyze-query-plan'

RELATED SCRIPTS:
04_planner_configuration.sql

HOW TO INTERPRET RESULTS:
If the second result set shows track_planning is off, the plan-time columns are structurally zero and prove nothing. When it is on, a pct_time_spent_planning above roughly 10% on a very high-frequency statement is significant: it usually means a query with many joins (planning cost grows steeply with join count and join_collapse_limit) or heavy use of unprepared statements where the application could use prepared statements instead. Most exchange OLTP statements should be overwhelmingly execution-bound.
===============================================================================
*/

-- pg_stat_statements presence check. This script only detects whether the
-- extension is already available; it never creates it.
SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements') AS pgss_available
\gset

\if :pgss_available
-- Planning time versus execution time per statement.
--
-- IMPORTANT: the plan-time columns are only populated when
-- pg_stat_statements.track_planning is on. It is OFF by default (it adds
-- measurable overhead on high-frequency workloads), so all-zero plan times
-- here mean "not being tracked", not "planning is free". Enable it
-- deliberately, for a bounded period, via the Aurora DB cluster parameter
-- group if planning cost is genuinely in question.
\set top_n 20
SELECT
    queryid,
    calls,
    round(total_plan_time::numeric, 2)                            AS total_plan_time_ms,
    round(mean_plan_time::numeric, 4)                             AS mean_plan_time_ms,
    round(total_exec_time::numeric, 2)                            AS total_exec_time_ms,
    round(mean_exec_time::numeric, 4)                             AS mean_exec_time_ms,
    round(
        100.0 * total_plan_time / NULLIF(total_plan_time + total_exec_time, 0), 2
    )                                                             AS pct_time_spent_planning,
    left(query, 200)                                              AS query_snippet
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
ORDER BY total_exec_time DESC
LIMIT :top_n;

-- Is planning time actually being tracked in this cluster?
SELECT
    name,
    setting,
    source,
    short_desc
FROM pg_settings
WHERE name IN ('pg_stat_statements.track_planning', 'pg_stat_statements.track', 'plan_cache_mode')
ORDER BY name;
\else
SELECT 'pg_stat_statements is not installed in this database, so statement-level '
       'statistics are unavailable. Ask an administrator to add '
       'pg_stat_statements to shared_preload_libraries in the Aurora DB cluster '
       'parameter group (a reboot is required for that change to take effect) '
       'and then run CREATE EXTENSION pg_stat_statements; in a change-managed '
       'session. Without it, query-level investigation must fall back to '
       'application-side latency metrics plus the catalog and table-level '
       'statistics used by the other scripts in this workflow.'  AS notice;
\endif
