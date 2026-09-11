/*
===============================================================================
SCRIPT NAME:
02_planning_time_check.sql

PURPOSE:
Checks whether the regression is in planning time rather than execution time.

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
Step 02 of workflow 'query-optimization/query-plan-regression'

RELATED SCRIPTS:
03_statistics_change_check.sql

HOW TO INTERPRET RESULTS:
If planning time is being tracked and has grown, look for structural causes rather than data causes: a partitioned table that has accumulated many partitions, an index count that has grown on a heavily queried table, or a join_collapse_limit change. Note plan_cache_mode: on the default auto setting, PostgreSQL switches a prepared statement to a cached generic plan after five executions when it looks safe, and that switch is one of the few regressions that leaves no trace anywhere except in the latency itself.
===============================================================================
*/

-- pg_stat_statements presence check. This script only detects whether the
-- extension is already available; it never creates it.
SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements') AS pgss_available
\gset

\if :pgss_available
-- Planning versus execution time. A regression in PLANNING time has
-- entirely different causes from one in execution time: more partitions to
-- consider, a higher join_collapse_limit, many more indexes to evaluate,
-- or a switch away from generic plans for a prepared statement.
--
-- These columns are only populated when pg_stat_statements.track_planning
-- is on, which is off by default. All-zero plan times mean "not tracked",
-- not "planning is free".
\set top_n 25
SELECT
    queryid,
    calls,
    round(total_plan_time::numeric, 2)                            AS total_plan_time_ms,
    round(mean_plan_time::numeric, 4)                             AS mean_plan_time_ms,
    round(mean_exec_time::numeric, 4)                             AS mean_exec_time_ms,
    round(
        (100.0 * total_plan_time / NULLIF(total_plan_time + total_exec_time, 0))::numeric, 2
    )                                                             AS pct_time_spent_planning,
    left(query, 200)                                              AS query_snippet
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
ORDER BY total_plan_time DESC NULLS LAST
LIMIT :top_n;

-- Settings that govern planning cost and generic-plan behaviour.
SELECT
    name,
    setting,
    source,
    short_desc
FROM pg_settings
WHERE name IN (
    'pg_stat_statements.track_planning',
    'pg_stat_statements.track',
    'plan_cache_mode',
    'join_collapse_limit',
    'from_collapse_limit',
    'geqo_threshold'
)
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
