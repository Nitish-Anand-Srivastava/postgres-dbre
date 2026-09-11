/*
===============================================================================
SCRIPT NAME:
05_write_rate_projection_proxy.sql

PURPOSE:
Provides a fallback growth estimate from insert counters and average row width for databases with no size history yet.

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
Step 05 of workflow 'storage-and-capacity/capacity-forecasting'

RELATED SCRIPTS:
06_capacity_forecast_worksheet.md

HOW TO INTERPRET RESULTS:
Use projected_growth_over_horizon only for relative prioritization between tables, never as an absolute number to quote. Read confidence_note on every row: a table with heavy deletes is systematically over-forecast here because the model ignores them entirely, and a statistics window shorter than a week is dominated by whatever happened to be running. avg_bytes_per_row is independently useful even when the projection is not -- it is the number you need to estimate the storage impact of a planned product change such as a new venue, a new instrument, or a longer retention requirement. If stats_reset is recent because of an Aurora failover, every rate here is understated and the script should be re-run after a representative period.
===============================================================================
*/

-- Fallback projection for a database where the size-history collector has
-- not been deployed yet.
--
-- METHOD AND ITS WEAKNESSES, STATED PLAINLY: derive average bytes per row
-- from current total relation size divided by the live row estimate, derive
-- an insert rate from n_tup_ins divided by the time since statistics were
-- last reset, and multiply the two out over the horizon. This is
-- deliberately cruder than the history-based projection in script 04 and
-- carries three extra assumptions:
--   1. average row width stays constant (wrong if payload columns are
--      growing, or if the table is bloated today and vacuumed tomorrow),
--   2. inserts dominate -- deletes and purges are ignored entirely, so an
--      actively purged table is over-forecast,
--   3. the workload since stats_reset is representative, which it is not
--      if the window included a market event, a backfill, or a failover.
-- Replace this with script 04 as soon as the collector has enough samples.
\set top_n 30
\set projection_days 180
SELECT
    s.schemaname                                                  AS schema_name,
    s.relname                                                     AS table_name,
    pg_size_pretty(pg_total_relation_size(s.relid))               AS current_total_size,
    s.n_live_tup,
    s.n_tup_ins,
    d.stats_reset,
    round(
        extract(epoch FROM (now() - d.stats_reset))::numeric / 86400.0, 2
    )                                                             AS stats_window_days,
    round(
        s.n_tup_ins::numeric
        / NULLIF(extract(epoch FROM (now() - d.stats_reset))::numeric
                 / 86400.0, 0), 0
    )                                                             AS avg_rows_inserted_per_day,
    round(
        pg_total_relation_size(s.relid)::numeric
        / NULLIF(s.n_live_tup, 0), 0
    )                                                             AS avg_bytes_per_row,
    :projection_days                                              AS projection_horizon_days,
    pg_size_pretty(round(
        (pg_total_relation_size(s.relid)::numeric / NULLIF(s.n_live_tup, 0))
        * (s.n_tup_ins::numeric
           / NULLIF(extract(epoch FROM (now() - d.stats_reset))::numeric
                    / 86400.0, 0))
        * :projection_days
    ))                                                            AS projected_growth_over_horizon,
    CASE
        WHEN s.n_tup_del > s.n_tup_ins / 2
            THEN 'OVER-FORECAST LIKELY -- this table is actively purged (high n_tup_del), which this model ignores'
        WHEN extract(epoch FROM (now() - d.stats_reset)) < 86400 * 7
            THEN 'LOW CONFIDENCE -- statistics window is under 7 days'
        ELSE 'USABLE AS A ROUGH ESTIMATE ONLY -- prefer 04_linear_projection_and_runway.sql once history exists'
    END                                                           AS confidence_note
FROM pg_stat_all_tables s
CROSS JOIN (
    SELECT stats_reset FROM pg_stat_database WHERE datname = current_database()
) d
WHERE s.schemaname NOT IN ('pg_catalog', 'information_schema')
  AND s.n_tup_ins > 0
  AND d.stats_reset IS NOT NULL
  AND s.n_live_tup > 0
ORDER BY pg_total_relation_size(s.relid) DESC
LIMIT :top_n;
