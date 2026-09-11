/*
===============================================================================
SCRIPT NAME:
02_index_consistency_across_partitions.sql

PURPOSE:
Checks whether every partition has the same set of indexes as the partitioned parent, to catch drift from manual per-partition changes.

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
Step 02 of workflow 'partitioning/partition-maintenance'

RELATED SCRIPTS:
../partition-existing-large-table/scripts/06_create_partitions_and_indexes.md

HOW TO INTERPRET RESULTS:
Partitions with a lower index_count than their siblings are missing an index -- cross-reference against the parent's index list and add the missing index CONCURRENTLY on that specific partition.
===============================================================================
*/

-- Compares each partition's index count against the parent's expected index
-- count, to catch a partition that is missing an index the others have
-- (commonly from a partition created before an index was added to the
-- parent, or an index build that failed on one specific partition).
\set schema_name 'public'
\set parent_table 'orders'
SELECT
    child.relname                                               AS partition_name,
    count(idx.indexrelid)                                        AS index_count
FROM pg_inherits i
JOIN pg_class parent ON parent.oid = i.inhparent
JOIN pg_class child ON child.oid = i.inhrelid
JOIN pg_namespace n ON n.oid = parent.relnamespace
LEFT JOIN pg_index idx ON idx.indrelid = child.oid
WHERE n.nspname = :'schema_name' AND parent.relname = :'parent_table'
GROUP BY child.relname
ORDER BY index_count ASC, child.relname;
