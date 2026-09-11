/*
===============================================================================
SCRIPT NAME:
03_statistics_change_check.sql

PURPOSE:
Checks when statistics were last refreshed on the tables involved, in both directions.

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
Step 03 of workflow 'query-optimization/query-plan-regression'

RELATED SCRIPTS:
04_index_state_check.sql, ../stale-statistics/README.md

HOW TO INTERPRET RESULTS:
Correlate last_analyze and last_autoanalyze against the moment the regression began. An ANALYZE at that moment is a prime suspect in both directions: statistics that went stale and produced a bad plan, or statistics that were refreshed and caused the planner to switch away from a plan that happened to be working well. The second case is uncomfortable but real -- the fix is then to make the estimate good enough that the planner chooses well with accurate statistics, never to leave statistics deliberately stale.
===============================================================================
*/

-- Tables whose planner statistics may be stale relative to how much the
-- table has changed since the last ANALYZE. n_mod_since_analyze counts
-- inserts+updates+deletes since the last analyze; a large value relative to
-- table size means the planner's row estimates (and therefore its join
-- order / index choice) can be significantly wrong.
\set top_n 30
SELECT
    schemaname                                                  AS schema_name,
    relname                                                     AS table_name,
    n_live_tup,
    n_mod_since_analyze,
    round(100.0 * n_mod_since_analyze / NULLIF(n_live_tup, 0), 2) AS pct_modified_since_analyze,
    last_analyze,
    last_autoanalyze
FROM pg_stat_all_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY pct_modified_since_analyze DESC NULLS LAST
LIMIT :top_n;
