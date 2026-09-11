/*
===============================================================================
SCRIPT NAME:
06_post_archive_vacuum.sql

PURPOSE:
Checks dead tuple accumulation after the batched deletion and confirms whether a manual VACUUM is warranted to reclaim space.

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
Step 06 of workflow 'archival-and-data-lifecycle/archive-large-table'

RELATED SCRIPTS:
../../vacuum-and-autovacuum/table-bloat/README.md

HOW TO INTERPRET RESULTS:
A large deletion produces a correspondingly large number of dead tuples; a manual `VACUUM (VERBOSE, ANALYZE) <table>;` after the batched delete completes reclaims that space for reuse and refreshes planner statistics promptly, rather than waiting for the next scheduled autovacuum pass.
===============================================================================
*/

-- Tables ranked by dead tuple ratio and absolute dead tuple count. High
-- dead-tuple ratios combined with a stale last_autovacuum timestamp are the
-- clearest sign that autovacuum is not keeping up with a table's write rate.
\set top_n 30
SELECT
    schemaname                                                  AS schema_name,
    relname                                                     AS table_name,
    n_live_tup,
    n_dead_tup,
    round(100.0 * n_dead_tup / NULLIF(n_live_tup + n_dead_tup, 0), 2) AS dead_tuple_pct,
    last_vacuum,
    last_autovacuum,
    last_analyze,
    last_autoanalyze,
    autovacuum_count,
    vacuum_count
FROM pg_stat_all_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY n_dead_tup DESC
LIMIT :top_n;
