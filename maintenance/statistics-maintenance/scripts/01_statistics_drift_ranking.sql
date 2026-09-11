/*
===============================================================================
SCRIPT NAME:
01_statistics_drift_ranking.sql

PURPOSE:
Ranks tables by how far their contents have drifted since the last ANALYZE, which is the primary input to every other decision in this workflow.

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
Step 01 of workflow 'maintenance/statistics-maintenance'

RELATED SCRIPTS:
02_per_table_autovacuum_and_analyze_settings.sql

HOW TO INTERPRET RESULTS:
Work top-down, but read the ratio rather than the raw count: the tables worth acting on are the large, actively written ones (orders, trades, ledger entries, deposit/withdrawal events) whose modified-row count is large in absolute terms, not the small lookup tables that can show an alarming percentage from a handful of rows. A NULL last_autoanalyze on a large, busy table means autoanalyze has never completed there -- that is an autovacuum capacity finding, not a threshold-tuning one.
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
