/*
===============================================================================
SCRIPT NAME:
01_confirm_archive_boundary.sql

PURPOSE:
Confirms the exact row count and boundary that will be affected by the approved retention cutoff, before any data movement begins.

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
Step 01 of workflow 'archival-and-data-lifecycle/archive-large-table'

RELATED SCRIPTS:
02_export_to_cold_storage.md

HOW TO INTERPRET RESULTS:
Record rows_to_archive as your ground-truth scope figure -- every later validation step (script 04) must reconcile against this exact number.
===============================================================================
*/

-- Confirms the exact scope of the archive operation: row count and date
-- range for rows older than the approved retention boundary. Ships with an
-- illustrative default (public.orders / created_at); edit the \set lines
-- below for your real candidate table -- the guard below means running
-- this unmodified prints an instructional notice instead of failing.
\set schema_name 'public'
\set table_name 'orders'
\set timestamp_column 'created_at'
\set retention_cutoff '2023-01-01'
SELECT to_regclass(:'schema_name' || '.' || :'table_name') IS NOT NULL AS target_table_exists
\gset

\if :target_table_exists
SELECT
    count(*)                                                    AS rows_to_archive,
    min(:"timestamp_column")                                      AS oldest_row_timestamp,
    max(:"timestamp_column")                                      AS newest_row_to_archive_timestamp
FROM :"schema_name".:"table_name"
WHERE :"timestamp_column" < :'retention_cutoff'::timestamptz;
\else
SELECT
    'Table ' || :'schema_name' || '.' || :'table_name' || ' does not exist '
    'in this database. Edit the schema_name/table_name/timestamp_column/ '
    'retention_cutoff \set lines above before relying on this report.'   AS notice;
\endif
