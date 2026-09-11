/*
===============================================================================
SCRIPT NAME:
04_index_scan_efficiency.sql

PURPOSE:
Measures how many tuples each index scan reads versus how many the executor actually keeps.

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
Step 04 of workflow 'query-optimization/inefficient-index-usage'

RELATED SCRIPTS:
05_sequential_scan_cross_check.sql

HOW TO INTERPRET RESULTS:
A high avg_entries_read_per_scan on an index meant to serve point lookups means it is being used for range scans it is not shaped for -- typically the leading column is not selective enough, so the scan walks a large portion of the index and the filter discards the rest. Adding the filtering column to the index, in the right position, usually converts that into a tight scan. Read pct_read_entries_fetched cautiously: a low value can equally mean an efficient index-only scan, so confirm against the plan before changing anything.
===============================================================================
*/

-- Index scan efficiency. idx_tup_read counts index entries read;
-- idx_tup_fetch counts live table rows actually fetched through those
-- entries. A large gap means the index is being scanned broadly and most
-- of what it returns is discarded -- the signature of an index whose
-- column order or column set does not match how the workload queries it.
--
-- (Index-only scans satisfy the query from the index alone and do not
-- increment idx_tup_fetch, so a high read/low fetch ratio can also be a
-- healthy index-only scan. Read this alongside the plan before concluding
-- the index is badly matched.)
\set top_n 30
SELECT
    s.schemaname                                                 AS schema_name,
    s.relname                                                    AS table_name,
    s.indexrelname                                               AS index_name,
    pg_size_pretty(pg_relation_size(s.indexrelid))                AS index_size,
    s.idx_scan,
    s.idx_tup_read,
    s.idx_tup_fetch,
    round(s.idx_tup_read::numeric / NULLIF(s.idx_scan, 0), 1)      AS avg_entries_read_per_scan,
    round(
        100.0 * s.idx_tup_fetch / NULLIF(s.idx_tup_read, 0), 2
    )                                                             AS pct_read_entries_fetched,
    s.last_idx_scan,
    ix.indisunique,
    ix.indisprimary,
    pg_get_indexdef(s.indexrelid)                                 AS index_definition
FROM pg_stat_all_indexes s
JOIN pg_index ix ON ix.indexrelid = s.indexrelid
WHERE s.schemaname NOT IN ('pg_catalog', 'information_schema')
  AND s.idx_scan > 0
ORDER BY (s.idx_tup_read - s.idx_tup_fetch) DESC
LIMIT :top_n;
