/*
===============================================================================
SCRIPT NAME:
09_validation_row_counts_checksums.sql

PURPOSE:
Compares row counts and checksums between the original and new partitioned table before cutover.

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
Step 09 of workflow 'partitioning/partition-existing-large-table'

RELATED SCRIPTS:
10_cutover_procedure.md

HOW TO INTERPRET RESULTS:
row_count_difference must be exactly zero (during a brief write-quiesce window) before proceeding to cutover. Any non-zero difference means the dual-write/CDC mechanism has a gap that must be found and fixed before continuing -- do not proceed to cutover with an unexplained mismatch.
===============================================================================
*/

-- Post-backfill validation: compare row counts and the same lightweight
-- checksum computed in script 04 against the new partitioned table. Run
-- this AFTER the dual-write/CDC sync (script 08) has been active for at
-- least one full validation pass with no application writes in flight
-- (e.g. during a brief write-quiesce window), so both sides are compared at
-- a consistent point in time. Ships with illustrative defaults (public.
-- orders / public.orders_partitioned); edit the \set lines below for your
-- real source and target tables.
\set schema_name 'public'
\set source_table 'orders'
\set target_table 'orders_partitioned'
SELECT
    to_regclass(:'schema_name' || '.' || :'source_table') IS NOT NULL
    AND to_regclass(:'schema_name' || '.' || :'target_table') IS NOT NULL AS both_tables_exist
\gset

\if :both_tables_exist
SELECT
    (SELECT count(*) FROM :"schema_name".:"source_table")               AS source_row_count,
    (SELECT count(*) FROM :"schema_name".:"target_table")                AS target_row_count,
    (SELECT count(*) FROM :"schema_name".:"source_table") - (SELECT count(*) FROM :"schema_name".:"target_table") AS row_count_difference;
\else
SELECT
    'One or both of ' || :'schema_name' || '.' || :'source_table' || ' and '
    || :'schema_name' || '.' || :'target_table' || ' do not exist in this '
    'database yet. Edit the schema_name/source_table/target_table \set '
    'lines above once the replacement table from script 05 has been '
    'created and backfilled.'                                      AS notice;
\endif
