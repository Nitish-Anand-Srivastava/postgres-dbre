/*
===============================================================================
SCRIPT NAME:
04_stored_statistics_for_table.sql

PURPOSE:
Inspects the actual stored distribution statistics for one suspect table.

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
Step 04 of workflow 'query-optimization/stale-statistics'

RELATED SCRIPTS:
05_refresh_statistics_safely.md

HOW TO INTERPRET RESULTS:
This is the direct evidence of drift. Compare what the planner stores against what you know is true now: if the exchange listed twenty new markets last month and the most common values list still contains only the old ones, the statistics predate that change and every predicate on that column is being estimated from history. An empty result set for a table you know has rows means no statistics exist at all for it, which is the most severe form of staleness.
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
