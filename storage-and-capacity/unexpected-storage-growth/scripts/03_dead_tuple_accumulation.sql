/*
===============================================================================
SCRIPT NAME:
03_dead_tuple_accumulation.sql

PURPOSE:
Quantifies dead tuples per table to test the most common hypothesis: that space is not being released rather than consumed.

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
Step 03 of workflow 'storage-and-capacity/unexpected-storage-growth'

RELATED SCRIPTS:
04_xmin_horizon_holders.sql

HOW TO INTERPRET RESULTS:
High dead tuple counts that persist through autovacuum cycles are the fingerprint of 'space not released', which is the single most common cause of unexpected growth. Do not respond by tuning autovacuum -- if the xmin horizon is held back, vacuum is running and correctly declining to remove tuples that a still-open transaction could theoretically still see. Go straight to scripts 04 and 05 to find what is holding it. A sudden jump in dead tuples on one table instead points at a bulk DELETE or UPDATE that ran unbatched, in which case the table names the job for you.
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
