/*
===============================================================================
SCRIPT NAME:
04_statistics_freshness.sql

PURPOSE:
Checks whether the planner's row estimates for the joined tables are based on current data.

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
Step 04 of workflow 'query-optimization/nested-loop-problems'

RELATED SCRIPTS:
05_join_strategy_settings.sql, ../stale-statistics/README.md

HOW TO INTERPRET RESULTS:
Underestimation on the outer side is what makes the planner choose a nested loop in the first place, and stale statistics are the most common source of underestimation. A table with a high pct_modified_since_analyze that participates in the problem join is the prime suspect: the planner may believe it holds the row count it had before the last backfill. A targeted ANALYZE is the cheapest possible fix and should be tried before any index work.
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
