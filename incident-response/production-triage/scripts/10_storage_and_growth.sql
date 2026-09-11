/*
===============================================================================
SCRIPT NAME:
10_storage_and_growth.sql

PURPOSE:
Step 10 of 10: database sizes and the largest tables, closing the checklist with the capacity picture.

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
Step 10 of workflow 'incident-response/production-triage'

RELATED SCRIPTS:
../../database-health/comprehensive-health-check/README.md

HOW TO INTERPRET RESULTS:
This rarely explains a sudden incident, which is exactly why it is last -- but it catches the ones that are genuinely capacity problems, and it is the cheapest place to notice a table growing without bound before it becomes its own page. On Aurora these are logical object sizes; billed cluster-volume usage is a CloudWatch value, not a SQL one.
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
