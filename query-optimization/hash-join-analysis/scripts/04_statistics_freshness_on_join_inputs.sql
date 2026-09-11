/*
===============================================================================
SCRIPT NAME:
04_statistics_freshness_on_join_inputs.sql

PURPOSE:
Checks whether the planner's size estimates for the joined tables are current.

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
Step 04 of workflow 'query-optimization/hash-join-analysis'

RELATED SCRIPTS:
05_test_memory_hypothesis_safely.md, ../stale-statistics/README.md

HOW TO INTERPRET RESULTS:
A spill caused by an underestimated build side is a statistics problem, and adding memory only masks it. If the tables in the problem join show a high pct_modified_since_analyze, run a targeted ANALYZE and re-capture the plan before touching work_mem at all -- a correct estimate frequently causes the planner to build the hash from the smaller input instead, which removes the spill without any memory change.
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
