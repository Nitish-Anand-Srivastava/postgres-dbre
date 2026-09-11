/*
===============================================================================
SCRIPT NAME:
01_partitions_outside_retention.sql

PURPOSE:
Identifies partitions whose range is fully outside the approved retention window.

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
Step 01 of workflow 'archival-and-data-lifecycle/archive-partition'

RELATED SCRIPTS:
02_detach_and_archive.md

HOW TO INTERPRET RESULTS:
Manually confirm which partition_bound values fall entirely before your approved retention cutoff; only fully-outside-window partitions should be detached.
===============================================================================
*/

-- Lists partitions of a given parent table with their bounds, to identify
-- which are fully outside the retention window and eligible for detach.
-- This query is safe to run unmodified: it filters pg_catalog data by name
-- (never a direct FROM/regclass reference to the parent table itself), so
-- an unmatched default parent_table simply returns zero rows rather than
-- failing -- edit the \set lines below to point at your real partitioned
-- parent table.
\set schema_name 'public'
\set parent_table 'orders'
SELECT
    child.relname                                               AS partition_name,
    pg_get_expr(child.relpartbound, child.oid)                    AS partition_bound,
    pg_size_pretty(pg_total_relation_size(child.oid))              AS partition_size
FROM pg_inherits i
JOIN pg_class parent ON parent.oid = i.inhparent
JOIN pg_class child ON child.oid = i.inhrelid
JOIN pg_namespace n ON n.oid = parent.relnamespace
WHERE n.nspname = :'schema_name' AND parent.relname = :'parent_table'
ORDER BY child.relname;
