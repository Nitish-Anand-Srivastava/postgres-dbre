/*
===============================================================================
SCRIPT NAME:
05_sequential_scan_cross_check.sql

PURPOSE:
Cross-checks tables where sequential scans dominate despite indexes being present.

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
Step 05 of workflow 'query-optimization/inefficient-index-usage'

RELATED SCRIPTS:
06_validate_index_change_safely.md, ../../tables-and-indexes/sequential-scan-investigation/README.md

HOW TO INTERPRET RESULTS:
A large table with heavy sequential scanning and a healthy set of indexes means the planner is declining to use them. The usual reasons, in order of frequency, are: a non-sargable predicate (a function or cast around the column), a type or collation mismatch, the wrong leading column, stale statistics making the index look unselective, and a cost configuration that overstates random I/O. The second result set catches the remaining case -- an index that is present but INVALID, which the planner ignores entirely while the application still pays for it on every write.
===============================================================================
*/

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

-- Indexes left in an INVALID state, almost always because a previous
-- CREATE INDEX CONCURRENTLY or REINDEX CONCURRENTLY failed partway through
-- (a killed session, statement_timeout, or deadlock). Invalid indexes are
-- not used by the planner but still consume storage and slow down writes,
-- so they should be dropped and, if needed, recreated concurrently.
SELECT
    n.nspname                                                   AS schema_name,
    c.relname                                                   AS table_name,
    i.relname                                                   AS index_name,
    pg_size_pretty(pg_relation_size(i.oid))                      AS wasted_size,
    pg_get_indexdef(ix.indexrelid)                               AS index_definition
FROM pg_index ix
JOIN pg_class c ON c.oid = ix.indrelid
JOIN pg_class i ON i.oid = ix.indexrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE NOT ix.indisvalid
ORDER BY pg_relation_size(i.oid) DESC;
