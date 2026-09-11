/*
===============================================================================
SCRIPT NAME:
03_table_and_index_activity_metrics.sql

PURPOSE:
Dead tuple ratios and vacuum timestamps per table, plus index size and scan-activity inventory.

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
Step 03 of workflow 'observability/postgres-metrics'

RELATED SCRIPTS:
04_io_and_checkpoint_metrics.sql

HOW TO INTERPRET RESULTS:
These two views are where vacuum debt and lost access paths first become visible, well before they show up as latency. Track dead_tuple_pct trend per table (not just its current value) -- a table whose ratio climbs for several consecutive collection intervals is losing the race against its write rate even if the absolute number still looks moderate.
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

-- Index size, scan counts, and a simple size-per-row proxy for bloat.
-- PostgreSQL 16+ also reports last_idx_scan/last_idx_tup_fetch/
-- last_idx_tup_read (timestamps) on pg_stat_all_indexes, which are included
-- here to show *when* an index was last actually useful, not just whether
-- idx_scan is currently zero since the last stats reset.
\set top_n 40
SELECT
    n.nspname                                                   AS schema_name,
    c.relname                                                   AS table_name,
    i.relname                                                   AS index_name,
    pg_size_pretty(pg_relation_size(i.oid))                      AS index_size,
    s.idx_scan,
    s.idx_tup_read,
    s.idx_tup_fetch,
    s.last_idx_scan,
    ix.indisunique,
    ix.indisprimary,
    ix.indisvalid
FROM pg_index ix
JOIN pg_class c ON c.oid = ix.indrelid
JOIN pg_class i ON i.oid = ix.indexrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_stat_all_indexes s ON s.indexrelid = ix.indexrelid
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY pg_relation_size(i.oid) DESC
LIMIT :top_n;
