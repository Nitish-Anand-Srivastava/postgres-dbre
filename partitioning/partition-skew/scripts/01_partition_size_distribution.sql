/*
===============================================================================
SCRIPT NAME:
01_partition_size_distribution.sql

PURPOSE:
Compares partition sizes across a partitioned table to identify skew.

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
Step 01 of workflow 'partitioning/partition-skew'

RELATED SCRIPTS:
../partition-performance/README.md

HOW TO INTERPRET RESULTS:
A single partition holding a dramatically disproportionate pct_of_total (well beyond what an even N-way split would predict) is skewed -- confirm whether this matches expected business skew or indicates a key-choice problem.
===============================================================================
*/

-- Size distribution across all partitions of a given parent table, sorted
-- largest first, to quantify skew.
\set schema_name 'public'
\set parent_table 'orders'
SELECT
    child.relname                                               AS partition_name,
    pg_size_pretty(pg_total_relation_size(child.oid))             AS partition_size,
    round(
        100.0 * pg_total_relation_size(child.oid) /
        NULLIF(sum(pg_total_relation_size(child.oid)) OVER (), 0),
        2
    )                                                            AS pct_of_total
FROM pg_inherits i
JOIN pg_class parent ON parent.oid = i.inhparent
JOIN pg_class child ON child.oid = i.inhrelid
JOIN pg_namespace n ON n.oid = parent.relnamespace
WHERE n.nspname = :'schema_name' AND parent.relname = :'parent_table'
ORDER BY pg_total_relation_size(child.oid) DESC;
