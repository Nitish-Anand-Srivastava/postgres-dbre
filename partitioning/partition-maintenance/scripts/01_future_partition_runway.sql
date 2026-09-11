/*
===============================================================================
SCRIPT NAME:
01_future_partition_runway.sql

PURPOSE:
Checks how many future partitions exist for a time-based partitioned table and how much runway remains.

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
Step 01 of workflow 'partitioning/partition-maintenance'

RELATED SCRIPTS:
02_index_consistency_across_partitions.sql

HOW TO INTERPRET RESULTS:
Confirm at least 1-2 future periods' worth of partitions already exist beyond the current date; if the highest partition_bound is approaching now(), create additional future partitions immediately.
===============================================================================
*/

-- Lists all partitions of a given partitioned parent table with their
-- range bounds, to assess remaining runway for future data.
\set schema_name 'public'
\set parent_table 'orders'
SELECT
    child.relname                                               AS partition_name,
    pg_get_expr(child.relpartbound, child.oid)                   AS partition_bound,
    pg_size_pretty(pg_total_relation_size(child.oid))             AS partition_size
FROM pg_inherits i
JOIN pg_class parent ON parent.oid = i.inhparent
JOIN pg_class child ON child.oid = i.inhrelid
JOIN pg_namespace n ON n.oid = parent.relnamespace
WHERE n.nspname = :'schema_name' AND parent.relname = :'parent_table'
ORDER BY child.relname;
