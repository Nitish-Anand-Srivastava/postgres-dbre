/*
===============================================================================
SCRIPT NAME:
04_row_count_baseline.sql

PURPOSE:
Captures the authoritative pre-migration row count and a lightweight checksum baseline for later validation.

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
Step 04 of workflow 'partitioning/partition-existing-large-table'

RELATED SCRIPTS:
05_create_partitioned_replacement_table.md

HOW TO INTERPRET RESULTS:
Record row_count and pk_checksum somewhere durable (a runbook ticket, not just your terminal scrollback) -- this is your ground truth for validation in script 09, taken before any backfill activity begins.
===============================================================================
*/

-- Baseline row count and a lightweight aggregate checksum (sum of hashtext
-- over primary key values) for the source table, to be compared against the
-- new partitioned table after backfill in script 09. Ships with an
-- illustrative default (public.orders / id); edit the \set lines below for
-- your real candidate table and primary key column.
\set schema_name 'public'
\set table_name 'orders'
\set primary_key_column 'id'
SELECT to_regclass(:'schema_name' || '.' || :'table_name') IS NOT NULL AS target_table_exists
\gset

\if :target_table_exists
SELECT
    count(*)                                                    AS row_count,
    sum(hashtext(:"primary_key_column"::text))                    AS pk_checksum
FROM :"schema_name".:"table_name";
\else
SELECT
    'Table ' || :'schema_name' || '.' || :'table_name' || ' does not exist '
    'in this database. Edit the schema_name/table_name/primary_key_column '
    '\set lines above to point at your real candidate table before '
    'recording a baseline.'                                       AS notice;
\endif
