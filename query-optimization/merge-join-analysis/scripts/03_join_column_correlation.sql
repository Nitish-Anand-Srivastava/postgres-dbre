/*
===============================================================================
SCRIPT NAME:
03_join_column_correlation.sql

PURPOSE:
Shows per-column statistics, especially physical correlation, for the join columns.

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
Step 03 of workflow 'query-optimization/merge-join-analysis'

RELATED SCRIPTS:
04_sort_and_join_settings.sql, ../cardinality-estimation/README.md

HOW TO INTERPRET RESULTS:
correlation near 1 or -1 means the table's physical row order closely follows that column's logical order, so an ordered index scan is sequential-like and cheap -- exactly the condition that makes merge join attractive. correlation near 0 means an ordered scan would jump randomly across the heap, and the planner will usually prefer a sequential scan plus an explicit sort. On an exchange, an append-only trades table is naturally near-perfectly correlated on its timestamp and primary key, while a heavily updated orders table often is not.
===============================================================================
*/

-- The planner's actual picture of one table's data distribution, as stored
-- by the last ANALYZE. This is the ground truth for "why did it estimate
-- 3 rows when there are 4 million". Edit the two \set lines first.
--
-- Reading pg_stats requires SELECT on the table or membership in
-- pg_read_all_stats (which pg_monitor includes). The relation name is only
-- compared in a WHERE clause, so a non-existent name yields zero rows
-- rather than an error.
--
-- NOTE: most_common_vals and histogram_bounds are declared as the
-- pseudo-type anyarray, which cannot be cast to text or passed to
-- array-processing functions. most_common_freqs is a concrete real[] with
-- exactly one entry per most-common value, so its length is used below to
-- report how many MCV entries were stored, and a simple NULL test reports
-- whether a histogram exists at all.
\set schema_name 'public'
\set table_name 'orders'
SELECT
    schemaname                                                   AS schema_name,
    tablename                                                    AS table_name,
    attname                                                      AS column_name,
    inherited,
    null_frac,
    avg_width,
    n_distinct,
    array_length(most_common_freqs, 1)                            AS mcv_entries,
    most_common_freqs[1]                                          AS most_common_value_frequency,
    (histogram_bounds IS NOT NULL)                                AS has_histogram,
    correlation
FROM pg_stats
WHERE schemaname = :'schema_name'
  AND tablename = :'table_name'
ORDER BY attname;
