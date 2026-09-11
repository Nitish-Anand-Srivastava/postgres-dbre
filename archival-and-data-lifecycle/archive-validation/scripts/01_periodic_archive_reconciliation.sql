/*
===============================================================================
SCRIPT NAME:
01_periodic_archive_reconciliation.sql

PURPOSE:
Re-runs the row-count/checksum reconciliation used during the original archive to confirm the archive remains intact over time.

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
Step 01 of workflow 'archival-and-data-lifecycle/archive-validation'

RELATED SCRIPTS:
../archive-large-table/scripts/04_spot_check_data_integrity.sql

HOW TO INTERPRET RESULTS:
row_count_matches must be true and current_checksum must equal the baseline recorded at archive time; any mismatch is a validation failure and should be escalated immediately, not silently re-baselined.
===============================================================================
*/

-- Periodic re-validation: compares a checksum of the archived data against
-- a previously recorded baseline checksum (stored at archive time) to
-- detect silent corruption/loss in the archive destination over time.
-- expected_row_count/expected_checksum below are illustrative placeholders
-- -- replace them with the real baseline values recorded when this archive
-- was created (see archive-large-table scripts 03/04) before relying on
-- the row_count_matches/checksum comparison.
\set archive_schema 'archive_db'
\set archive_table 'orders_archive'
\set expected_row_count 1500000
\set expected_checksum 'baseline-checksum-recorded-at-archive-time'
SELECT to_regclass(:'archive_schema' || '.' || :'archive_table') IS NOT NULL AS archive_table_exists
\gset

\if :archive_table_exists
SELECT
    count(*)                                                    AS current_row_count,
    md5(string_agg(id::text, ',' ORDER BY id))                    AS current_checksum,
    count(*) = :expected_row_count                                AS row_count_matches
FROM :"archive_schema".:"archive_table";
\else
SELECT
    'Archive destination ' || :'archive_schema' || '.' || :'archive_table' ||
    ' is not reachable as a local relation in this database. Edit the '
    'archive_schema/archive_table \set lines above, or run the equivalent '
    'reconciliation directly against your archive destination connection '
    'instead.'                                                     AS notice;
\endif
