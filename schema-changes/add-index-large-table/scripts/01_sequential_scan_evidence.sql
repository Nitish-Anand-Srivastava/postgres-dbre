/*
===============================================================================
SCRIPT NAME:
01_sequential_scan_evidence.sql

PURPOSE:
Establishes whether there is real evidence of expensive sequential scans justifying a new index on a large table.

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
Step 01 of workflow 'schema-changes/add-index-large-table'

RELATED SCRIPTS:
02_existing_index_inventory.sql

HOW TO INTERPRET RESULTS:
This is the evidence step and it should be allowed to say no. A high seq_scan count by itself proves nothing -- small lookup tables are scanned sequentially by design and that is genuinely faster than using an index. What justifies an index on a large table is a high avg_rows_per_seq_scan combined with a large table_size and a low idx_scan, which together describe a query repeatedly reading most of a very large relation. If the target table does not appear prominently here, pause and re-examine the assumption that an index is the right fix; the answer may be a better predicate, a partition key, or moving the query off the OLTP path entirely.
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
