/*
===============================================================================
SCRIPT NAME:
01_dead_tuples_ranked.sql

PURPOSE:
Ranks tables by dead tuple count and ratio.

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
Step 01 of workflow 'vacuum-and-autovacuum/dead-tuples'

RELATED SCRIPTS:
../table-bloat/README.md

HOW TO INTERPRET RESULTS:
Cross-reference dead_tuple_pct against the table's write pattern -- a high ratio on a rarely-updated table is more concerning than the same ratio on a known-hot table between vacuum cycles.
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
