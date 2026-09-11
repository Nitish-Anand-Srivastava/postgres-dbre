/*
===============================================================================
SCRIPT NAME:
02_partition_sizing_estimate.sql

PURPOSE:
Estimates resulting partition sizes given a proposed bucketing granularity, to avoid creating either too many tiny partitions or too few oversized ones.

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
Step 02 of workflow 'partitioning/partition-existing-large-table'

RELATED SCRIPTS:
03_dependent_objects_inventory.sql

HOW TO INTERPRET RESULTS:
If avg_size_per_partition_pretty is far outside the tens-of-GB heuristic range, revisit the bucketing granularity from script 01 before finalizing the partition scheme.
===============================================================================
*/

-- Estimates average partition size in bytes given the current table's total
-- size and the row-distribution bucket counts gathered in script 01.
-- A commonly cited practical guideline is to keep individual partitions in
-- the low tens-of-GB range and avoid exceeding a few thousand total
-- partitions per table (planner and catalog overhead both grow with
-- partition count) -- treat this as a starting heuristic, not a hard rule,
-- and validate against your own query latency requirements.
\set schema_name 'public'
\set table_name 'orders'
\set proposed_partition_count 24
SELECT to_regclass(:'schema_name' || '.' || :'table_name') IS NOT NULL AS target_table_exists
\gset

\if :target_table_exists
SELECT
    pg_size_pretty(pg_total_relation_size(to_regclass(:'schema_name' || '.' || :'table_name'))) AS current_total_size,
    pg_total_relation_size(to_regclass(:'schema_name' || '.' || :'table_name')) / NULLIF(:proposed_partition_count, 0) AS avg_bytes_per_partition_estimate,
    pg_size_pretty((pg_total_relation_size(to_regclass(:'schema_name' || '.' || :'table_name')) / NULLIF(:proposed_partition_count, 0))::bigint) AS avg_size_per_partition_pretty;
\else
SELECT
    'Table ' || :'schema_name' || '.' || :'table_name' || ' does not exist '
    'in this database. Edit the schema_name/table_name \set lines above to '
    'point at your real partitioning candidate table.'              AS notice;
\endif
