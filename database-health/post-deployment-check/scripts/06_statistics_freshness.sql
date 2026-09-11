/*
===============================================================================
SCRIPT NAME:
06_statistics_freshness.sql

PURPOSE:
Checks how stale planner statistics are on tables the migration modified in bulk.

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
Step 06 of workflow 'database-health/post-deployment-check'

RELATED SCRIPTS:
07_connection_and_lock_behavior.sql, ../../query-optimization/stale-statistics/README.md

HOW TO INTERPRET RESULTS:
A migration that backfilled or bulk-updated rows leaves n_mod_since_analyze high and last_analyze stale, so the planner is choosing plans from a picture of the data that no longer exists. This is the most common cause of a plan regression that appears minutes after a successful migration. The fix is a targeted ANALYZE on those tables, executed as a change-managed action.
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
