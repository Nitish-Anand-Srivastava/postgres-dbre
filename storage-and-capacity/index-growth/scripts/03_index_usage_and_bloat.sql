/*
===============================================================================
SCRIPT NAME:
03_index_usage_and_bloat.sql

PURPOSE:
Pairs index size with scan counters and last-scan timestamps so cost and value can be judged in the same view.

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
Step 03 of workflow 'storage-and-capacity/index-growth'

RELATED SCRIPTS:
04_unused_index_candidates.sql

HOW TO INTERPRET RESULTS:
Read size and usage together: a large index with millions of scans is earning its keep, and a large index with a last_idx_scan months in the past is not. last_idx_scan is the more reliable of the two signals because it is a timestamp rather than a counter -- counters reset on failover, timestamps simply stop advancing. Also check indisvalid here: a false value means a failed build left the index unusable while still consuming its full size.
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
