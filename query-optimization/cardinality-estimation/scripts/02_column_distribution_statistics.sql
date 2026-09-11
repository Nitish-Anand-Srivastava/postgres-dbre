/*
===============================================================================
SCRIPT NAME:
02_column_distribution_statistics.sql

PURPOSE:
Shows the planner's stored distribution statistics for every column of one table.

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
Step 02 of workflow 'query-optimization/cardinality-estimation'

RELATED SCRIPTS:
03_statistics_targets.sql

HOW TO INTERPRET RESULTS:
This is exactly what the planner knows. Compare each column against your knowledge of the business data: if you know one market symbol carries 40% of trades, most_common_value_frequency should show roughly that, and if it does not, the statistics are either stale or too coarse. A negative n_distinct close to -1 means nearly every value is unique; a positive value far below the true distinct count on a large table is a sampling failure and is a candidate for an explicit override. Note any column with a high null_frac, since predicates on it will be estimated very differently from what a naive reading suggests.
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
