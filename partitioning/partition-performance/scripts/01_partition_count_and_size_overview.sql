/*
===============================================================================
SCRIPT NAME:
01_partition_count_and_size_overview.sql

PURPOSE:
Overview of total partition count and size distribution, to assess whether the granularity itself is appropriate.

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
Step 01 of workflow 'partitioning/partition-performance'

RELATED SCRIPTS:
../partition-pruning/README.md

HOW TO INTERPRET RESULTS:
A partition_count in the thousands with a small avg_partition_size suggests over-partitioning; consider a coarser granularity (e.g. monthly instead of daily) going forward.
===============================================================================
*/

-- Total partition count and aggregate size for a given partitioned table --
-- a very high partition count (thousands) increases planner/catalog
-- overhead for every query touching the table, even with effective pruning.
\set schema_name 'public'
\set parent_table 'orders'
SELECT
    count(*)                                                    AS partition_count,
    pg_size_pretty(sum(pg_total_relation_size(child.oid)))        AS total_size,
    pg_size_pretty(avg(pg_total_relation_size(child.oid))::bigint) AS avg_partition_size
FROM pg_inherits i
JOIN pg_class parent ON parent.oid = i.inhparent
JOIN pg_class child ON child.oid = i.inhrelid
JOIN pg_namespace n ON n.oid = parent.relnamespace
WHERE n.nspname = :'schema_name' AND parent.relname = :'parent_table';
