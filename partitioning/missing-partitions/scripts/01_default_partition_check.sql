/*
===============================================================================
SCRIPT NAME:
01_default_partition_check.sql

PURPOSE:
Checks whether a DEFAULT partition exists and how much data it currently holds.

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
Step 01 of workflow 'partitioning/missing-partitions'

RELATED SCRIPTS:
../partition-maintenance/README.md

HOW TO INTERPRET RESULTS:
A non-trivial or growing size here confirms rows are landing in the default partition instead of a specific one -- identify their actual partition-key values and create the missing specific partition(s).
===============================================================================
*/

-- Identifies the DEFAULT partition (if any) of a given partitioned table
-- and its current size -- a growing default partition is a leading
-- indicator that specific partitions are missing for arriving data.
\set schema_name 'public'
\set parent_table 'orders'
SELECT
    child.relname                                               AS default_partition_name,
    pg_size_pretty(pg_total_relation_size(child.oid))             AS size,
    (SELECT count(*) FROM pg_class WHERE oid = child.oid)          AS exists_check
FROM pg_inherits i
JOIN pg_class parent ON parent.oid = i.inhparent
JOIN pg_class child ON child.oid = i.inhrelid
JOIN pg_namespace n ON n.oid = parent.relnamespace
WHERE n.nspname = :'schema_name' AND parent.relname = :'parent_table'
  AND pg_get_expr(child.relpartbound, child.oid) = 'DEFAULT';
