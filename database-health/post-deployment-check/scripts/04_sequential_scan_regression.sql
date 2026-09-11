/*
===============================================================================
SCRIPT NAME:
04_sequential_scan_regression.sql

PURPOSE:
Finds tables where sequential scans now dominate, the signature of a lost or unusable index.

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
Step 04 of workflow 'database-health/post-deployment-check'

RELATED SCRIPTS:
05_invalid_indexes.sql, ../../tables-and-indexes/sequential-scan-investigation/README.md

HOW TO INTERPRET RESULTS:
A large table with a high and newly growing seq_tup_read is the clearest post-deployment red flag: the access path the application relied on is gone or is no longer chosen. Compare seq_scan against idx_scan for the tables the migration touched. Small reference tables such as markets or fee_tiers appearing here is normal and not a finding.
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
