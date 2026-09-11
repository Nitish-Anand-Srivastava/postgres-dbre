/*
===============================================================================
SCRIPT NAME:
01_table_growth_and_age_profile.sql

PURPOSE:
Checks table size and estimates the age distribution of its data via a candidate timestamp column.

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
Step 01 of workflow 'archival-and-data-lifecycle/investigate-archiving-candidate'

RELATED SCRIPTS:
02_recent_vs_historical_query_pattern.sql

HOW TO INTERPRET RESULTS:
A large fraction of rows in the oldest age buckets confirms the table has substantial historical data that is a candidate for archiving, subject to compliance-approved retention.
===============================================================================
*/

-- Row count by age bucket for a candidate archival table, to understand how
-- much of the table is 'old' vs. 'recent' by a chosen timestamp column.
-- Ships with an illustrative default (public.orders / created_at); edit the
-- \set lines below to point at your real candidate table. The to_regclass
-- guard below means running this unmodified against a database that does
-- not have that default table prints an instructional notice instead of
-- failing with "relation does not exist".
\set schema_name 'public'
\set table_name 'orders'
\set timestamp_column 'created_at'
SELECT to_regclass(:'schema_name' || '.' || :'table_name') IS NOT NULL AS target_table_exists
\gset

\if :target_table_exists
SELECT
    width_bucket(
        extract(epoch FROM now() - :"timestamp_column"),
        0, extract(epoch FROM interval '3 years'), 12
    )                                                            AS age_bucket_quarter,
    count(*)                                                    AS row_count
FROM :"schema_name".:"table_name"
GROUP BY 1
ORDER BY 1;
\else
SELECT
    'Table ' || :'schema_name' || '.' || :'table_name' || ' does not exist '
    'in this database. Edit the schema_name/table_name/timestamp_column '
    '\set lines above to point at your real archival candidate table '
    'before relying on this report.'                              AS notice;
\endif
