/*
===============================================================================
SCRIPT NAME:
01_statistics_freshness.sql

PURPOSE:
Ranks tables by how much they have changed since their last ANALYZE.

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
Step 01 of workflow 'query-optimization/cardinality-estimation'

RELATED SCRIPTS:
02_column_distribution_statistics.sql

HOW TO INTERPRET RESULTS:
Rule this out before anything else: a high pct_modified_since_analyze combined with a stale last_analyze means the planner is estimating from a picture of the table that no longer exists, and no amount of statistics-target tuning will help until that is corrected. On a very large exchange table the default autoanalyze threshold of 10% of rows can represent tens of millions of modifications, so a table can be badly stale while still technically within policy.
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
