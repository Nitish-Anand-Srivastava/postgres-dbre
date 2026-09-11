/*
===============================================================================
SCRIPT NAME:
06_statistics_freshness.sql

PURPOSE:
Checks planner statistics freshness, since a row-count misestimate causes spills that no amount of extra memory will prevent.

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
Step 06 of workflow 'storage-and-capacity/temp-file-growth'

RELATED SCRIPTS:
../../query-optimization/stale-statistics/README.md

HOW TO INTERPRET RESULTS:
This is the cheapest possible fix and is frequently the real cause, so do not skip it. When the planner underestimates the build side of a hash join it sizes the hash table from that wrong estimate and spills mid-execution regardless of how much work_mem is available -- raising memory simply moves the cliff. A high pct_modified_since_analyze on any table involved in the spilling statements from script 03 means you should run ANALYZE on those tables and re-measure before considering any memory change. Stale statistics on a fast-growing trade or ledger table are extremely common, because the default autoanalyze scale factor triggers proportionally less often as the table grows.
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
