/*
===============================================================================
SCRIPT NAME:
01_statistics_freshness_ranked.sql

PURPOSE:
Ranks tables by how far their statistics have drifted since the last ANALYZE.

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
Step 01 of workflow 'query-optimization/stale-statistics'

RELATED SCRIPTS:
02_analyze_counters_and_never_analyzed.sql

HOW TO INTERPRET RESULTS:
Read pct_modified_since_analyze together with n_live_tup and the analyze timestamps. Anything above roughly 20% on a table that participates in latency-sensitive queries is worth refreshing; anything above 50% means the planner is working from a substantially different table than the one that exists. A NULL in both last_analyze and last_autoanalyze on a populated table is the most severe case: the planner has never had real statistics for it at all.
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
