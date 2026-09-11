/*
===============================================================================
SCRIPT NAME:
02_index_bloat_and_usage.sql

PURPOSE:
Surfaces index size, scan counts, and last-used timestamps to catch both bloated and simply-unused indexes as part of the routine review.

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
Step 02 of workflow 'maintenance/routine-maintenance-checklist'

RELATED SCRIPTS:
03_statistics_freshness.sql

HOW TO INTERPRET RESULTS:
An index with idx_scan = 0 (or a last_idx_scan far in the past) across several checklist runs is a candidate for tables-and-indexes/unused-indexes; an index that is large relative to its table without an obvious reason is a candidate for reindex-strategy.
===============================================================================
*/

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
