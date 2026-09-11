/*
===============================================================================
SCRIPT NAME:
03_validate_export_row_counts.sql

PURPOSE:
Compares the exported row count against the confirmed source scope from script 01.

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
Step 03 of workflow 'archival-and-data-lifecycle/archive-large-table'

RELATED SCRIPTS:
04_spot_check_data_integrity.sql

HOW TO INTERPRET RESULTS:
exported_row_count MUST equal script 01's rows_to_archive exactly. Any difference means the export is incomplete -- investigate and re-export before proceeding to deletion under any circumstances.
===============================================================================
*/

-- Run the equivalent count against the ARCHIVE destination (via postgres_fdw/
-- dblink, or by querying the destination database directly) and compare
-- against the source count captured in script 01's rows_to_archive value.
-- This assumes the archive destination is reachable as a local relation
-- (e.g. a postgres_fdw foreign table) named archive_schema.archive_table --
-- edit the \set lines below to match your real archive destination.
\set archive_schema 'archive_db'
\set archive_table 'orders_archive'
\set timestamp_column 'created_at'
\set retention_cutoff '2023-01-01'
SELECT to_regclass(:'archive_schema' || '.' || :'archive_table') IS NOT NULL AS archive_table_exists
\gset

\if :archive_table_exists
SELECT count(*) AS exported_row_count
FROM :"archive_schema".:"archive_table"
WHERE :"timestamp_column" < :'retention_cutoff'::timestamptz;
\else
SELECT
    'Archive destination ' || :'archive_schema' || '.' || :'archive_table' ||
    ' is not reachable as a local relation in this database. Edit the '
    'archive_schema/archive_table \set lines above, or run the equivalent '
    'COUNT directly against your archive destination connection instead.' AS notice;
\endif
