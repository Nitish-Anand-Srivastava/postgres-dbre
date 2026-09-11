/*
===============================================================================
SCRIPT NAME:
02_database_and_table_sizes.sql

PURPOSE:
Captures the logical footprint of every database and the largest tables in the current database.

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
Step 02 of workflow 'database-health/comprehensive-health-check'

RELATED SCRIPTS:
03_database_activity_counters.sql, ../../database-health/capacity-health-check/README.md

HOW TO INTERPRET RESULTS:
Compare both result sets against the previous health check to derive a growth rate. On an exchange, the expected shape is trades, ledger_entries, order_book_snapshots, and audit/event tables dominating, with reference tables (markets, instruments, fee_tiers) staying small. A reference or configuration table appearing in the largest-tables list is a strong signal of unintended row accumulation or severe bloat.
===============================================================================
*/

-- Size of every database in the cluster. On Aurora, this reflects logical
-- object size as PostgreSQL reports it; actual billed storage is tracked
-- separately by the Aurora storage layer (see AWS Console/CloudWatch
-- VolumeBytesUsed, not a SQL-visible value) because Aurora storage grows in
-- 10GiB increments and is shared/compressed across the cluster's
-- replicas.
SELECT
    datname,
    pg_size_pretty(pg_database_size(datname))                     AS database_size,
    pg_database_size(datname)                                     AS database_size_bytes
FROM pg_database
WHERE datallowconn
ORDER BY pg_database_size(datname) DESC;

-- Largest tables in the current database by total size (heap + indexes +
-- TOAST), which is what actually matters for storage capacity planning and
-- I/O footprint.
\set top_n 30
SELECT
    n.nspname                                                   AS schema_name,
    c.relname                                                   AS table_name,
    pg_size_pretty(pg_relation_size(c.oid))                       AS heap_size,
    pg_size_pretty(pg_indexes_size(c.oid))                        AS index_size,
    pg_size_pretty(pg_total_relation_size(c.oid))                 AS total_size,
    c.reltuples::bigint                                          AS estimated_row_count
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY pg_total_relation_size(c.oid) DESC
LIMIT :top_n;
