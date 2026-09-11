/*
===============================================================================
SCRIPT NAME:
01_partition_key_distribution.sql

PURPOSE:
Analyzes the data distribution of the chosen candidate partition key to validate range/list boundary choices and detect skew.

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
Step 01 of workflow 'partitioning/partition-existing-large-table'

RELATED SCRIPTS:
02_partition_sizing_estimate.sql

HOW TO INTERPRET RESULTS:
Roughly even row_count across buckets supports range partitioning by that time unit; heavy skew in a small number of buckets suggests either a different bucket granularity or a different partition key/strategy (e.g. hash) is more appropriate.
===============================================================================
*/

-- Distribution of the candidate partition key column, to validate proposed
-- range boundaries (or list values) and detect skew that would create an
-- unevenly sized set of partitions. Ships with an illustrative default
-- (public.orders / created_at); edit the \set lines below for your real
-- candidate table and key. The to_regclass guard means running this
-- unmodified against a database without that default table prints an
-- instructional notice instead of failing.
\set schema_name 'public'
\set table_name 'orders'
\set partition_key_column 'created_at'
SELECT to_regclass(:'schema_name' || '.' || :'table_name') IS NOT NULL AS target_table_exists
\gset

\if :target_table_exists
SELECT
    date_trunc('month', :"partition_key_column")                  AS bucket,
    count(*)                                                  AS row_count
FROM :"schema_name".:"table_name"
GROUP BY 1
ORDER BY 1;
-- NOTE: date_trunc('month', ...) assumes a timestamp partition key
-- (range partitioning). For a non-time key (list/hash partitioning, e.g.
-- tenant_id), replace the bucket expression and GROUP BY with the raw
-- partition_key_column value instead -- the bucketing strategy is
-- inherently table- and key-specific.
\else
SELECT
    'Table ' || :'schema_name' || '.' || :'table_name' || ' does not exist '
    'in this database. Edit the schema_name/table_name/partition_key_column '
    '\set lines above to point at your real partitioning candidate table.' AS notice;
\endif
