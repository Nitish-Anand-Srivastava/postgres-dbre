/*
===============================================================================
SCRIPT NAME:
05_statistics_and_scan_regression.sql

PURPOSE:
Checks whether a release backfill invalidated planner statistics, or whether a new access pattern is driving sequential scans on large tables.

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
Step 05 of workflow 'incident-response/post-deployment-incident'

RELATED SCRIPTS:
06_rollback_decision_runbook.md

HOW TO INTERPRET RESULTS:
A high pct_modified_since_analyze immediately after a release means a backfill ran and the planner's row estimates are now wrong, which can flip plans on statements that were fine an hour ago. A large table with a high seq_tup_read and a low idx_scan is the signature of a new query with no supporting index.
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

-- Tables where sequential scans dominate over index scans, weighted by
-- table size, to prioritize the biggest opportunity first. A high seq_scan
-- count alone is not necessarily bad (small lookup tables are often scanned
-- sequentially by design and that is faster than an index scan) -- the
-- seq_tup_read/seq_scan ratio and table size are what indicate a genuinely
-- expensive full-table scan pattern.
\set top_n 30
SELECT
    schemaname                                                  AS schema_name,
    relname                                                     AS table_name,
    seq_scan,
    seq_tup_read,
    round(seq_tup_read::numeric / NULLIF(seq_scan, 0), 0)         AS avg_rows_per_seq_scan,
    idx_scan,
    pg_size_pretty(pg_relation_size(relid))                       AS table_size,
    n_live_tup
FROM pg_stat_all_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
  AND seq_scan > 0
ORDER BY seq_tup_read DESC
LIMIT :top_n;
