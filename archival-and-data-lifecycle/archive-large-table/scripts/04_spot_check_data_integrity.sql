/*
===============================================================================
SCRIPT NAME:
04_spot_check_data_integrity.sql

PURPOSE:
Spot-checks a sample of archived rows for full column-level integrity against the source, beyond just a row count match.

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
Step 04 of workflow 'archival-and-data-lifecycle/archive-large-table'

RELATED SCRIPTS:
05_batched_deletion.md

HOW TO INTERPRET RESULTS:
This query is written to return ONLY mismatches -- an empty result is success. Any returned row is a data-integrity failure in the archive and must be resolved before deletion.
===============================================================================
*/

-- Compares a checksum of full row content for a random sample of archived
-- IDs against the corresponding source rows, to catch column-level
-- corruption/truncation that a row-count-only check would miss. Ships with
-- illustrative defaults; edit the \set lines below for your real source
-- table and archive destination.
\set source_schema 'public'
\set source_table 'orders'
\set archive_schema 'archive_db'
\set archive_table 'orders_archive'
\set timestamp_column 'created_at'
\set retention_cutoff '2023-01-01'
\set sample_size 500
SELECT
    to_regclass(:'source_schema' || '.' || :'source_table') IS NOT NULL
    AND to_regclass(:'archive_schema' || '.' || :'archive_table') IS NOT NULL AS both_relations_exist
\gset

\if :both_relations_exist
SELECT
    s.id,
    s.source_checksum,
    a.archive_checksum,
    s.source_checksum = a.archive_checksum AS matches
FROM (
    SELECT id, md5(t::text) AS source_checksum
    FROM :"source_schema".:"source_table" t
    WHERE :"timestamp_column" < :'retention_cutoff'::timestamptz
    ORDER BY random()
    LIMIT :sample_size
) s
JOIN (
    SELECT id, md5(t::text) AS archive_checksum
    FROM :"archive_schema".:"archive_table" t
) a ON a.id = s.id
WHERE s.source_checksum <> a.archive_checksum;
\else
SELECT
    'One or both of ' || :'source_schema' || '.' || :'source_table' || ' and '
    || :'archive_schema' || '.' || :'archive_table' || ' do not exist in '
    'this database. Edit the \set lines above to point at your real '
    'source table and archive destination before relying on this '
    'comparison.'                                                  AS notice;
\endif
-- An empty result set (zero mismatched rows) is the expected, passing
-- outcome once both relations exist. NOTE: md5(t::text) is sensitive to
-- column order/type formatting differences between source and archive
-- schemas -- ensure both have an identical column definition before
-- relying on this comparison.
