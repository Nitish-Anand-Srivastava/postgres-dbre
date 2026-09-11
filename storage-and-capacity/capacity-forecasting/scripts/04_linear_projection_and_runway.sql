/*
===============================================================================
SCRIPT NAME:
04_linear_projection_and_runway.sql

PURPOSE:
Projects each relation forward linearly from its measured growth rate and computes days-to-threshold runway.

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
Step 04 of workflow 'storage-and-capacity/capacity-forecasting'

RELATED SCRIPTS:
05_write_rate_projection_proxy.sql

HOW TO INTERPRET RESULTS:
Read days_until_threshold_at_current_rate as a triage signal rather than a deadline, and always read confidence_note next to it -- a ninety-day runway derived from four days of samples is noise dressed up as a number. Under ninety days means schedule remediation immediately, because partitioning or archival on a large production table realistically takes months from design to cutover. Over a year means record it and re-review next quarter. A NULL or negative growth rate usually means a purge or archival ran inside the window rather than that the table is stable, so confirm with the owning team before recording anything as 'not growing'. Adjust lookback_days, projection_days, and table_threshold_gb at the top to match your review cadence and your agreed thresholds.
===============================================================================
*/

-- Naive linear capacity projection from the size-history collector.
--
-- METHOD, STATED PLAINLY: take the earliest and latest size sample for each
-- relation inside the lookback window, divide the difference by the elapsed
-- days to get bytes/day, and extend that rate forward. That is the entire
-- model. It assumes the observed rate continues unchanged, which is exactly
-- what an exchange workload does not do around listings, market events, and
-- volatility spikes. Use the output to prioritize remediation and to buy
-- lead time -- never as a commitment or an SLA.
--
-- The tracking table is optional infrastructure created by the
-- growth-monitoring collector, not a built-in catalog, so to_regclass() is
-- used to detect its absence. A bare FROM or a ::regclass cast would fail
-- at analysis time with "relation does not exist" before the guard could
-- ever run.
--
-- Note the ::numeric cast on table_threshold_gb: the psql variable is
-- substituted as a bare int4 literal, and "2000 * 1024 * 1024 * 1024"
-- overflows int4 (max ~2.1 billion) and raises "integer out of range"
-- unless numeric arithmetic is forced first.
\set tracking_table 'dba_toolkit.table_size_history'
\set lookback_days 30
\set projection_days 180
\set table_threshold_gb 2000
SELECT to_regclass(:'tracking_table') IS NOT NULL                 AS tracking_table_exists
\gset

\if :tracking_table_exists
WITH sized AS (
    SELECT
        schema_name,
        table_name,
        captured_at,
        size_bytes,
        min(captured_at) OVER w                                   AS first_capture,
        max(captured_at) OVER w                                   AS last_capture
    FROM dba_toolkit.table_size_history
    WHERE captured_at > now() - make_interval(days => :lookback_days)
    WINDOW w AS (PARTITION BY schema_name, table_name)
),
endpoints AS (
    SELECT
        schema_name,
        table_name,
        max(first_capture)                                        AS first_capture,
        max(last_capture)                                         AS last_capture,
        max(size_bytes) FILTER (WHERE captured_at = first_capture) AS start_bytes,
        max(size_bytes) FILTER (WHERE captured_at = last_capture)  AS end_bytes
    FROM sized
    GROUP BY schema_name, table_name
),
rates AS (
    SELECT
        schema_name,
        table_name,
        start_bytes,
        end_bytes,
        (extract(epoch FROM (last_capture - first_capture)) / 86400.0)::numeric
                                                                  AS window_days,
        (end_bytes - start_bytes)::numeric
            / NULLIF((extract(epoch FROM (last_capture - first_capture))
                      / 86400.0)::numeric, 0)                     AS growth_bytes_per_day
    FROM endpoints
)
SELECT
    schema_name,
    table_name,
    round(window_days, 1)                                         AS observed_window_days,
    pg_size_pretty(start_bytes)                                   AS size_at_window_start,
    pg_size_pretty(end_bytes)                                     AS size_now,
    pg_size_pretty(round(growth_bytes_per_day))                   AS avg_growth_per_day,
    :projection_days                                              AS projection_horizon_days,
    pg_size_pretty(
        round(end_bytes + growth_bytes_per_day * :projection_days)
    )                                                             AS projected_size_at_horizon,
    :table_threshold_gb                                           AS threshold_gb,
    CASE
        WHEN growth_bytes_per_day IS NULL OR growth_bytes_per_day <= 0
            THEN NULL
        ELSE round(
            ((:table_threshold_gb::numeric * 1024 * 1024 * 1024) - end_bytes)
            / growth_bytes_per_day, 0)
    END                                                           AS days_until_threshold_at_current_rate,
    CASE
        WHEN window_days < 7 THEN 'LOW CONFIDENCE -- under 7 days of history'
        WHEN window_days < 30 THEN 'MODERATE CONFIDENCE -- under 30 days of history'
        ELSE 'REASONABLE CONFIDENCE -- 30+ days of history'
    END                                                           AS confidence_note
FROM rates
WHERE window_days > 0
ORDER BY growth_bytes_per_day DESC NULLS LAST;
\else
SELECT
    'No size history is available, because ' || :'tracking_table' || ' does '
    'not exist in this database. A linear projection needs at least two '
    'point-in-time samples and history cannot be reconstructed after the '
    'fact, so deploy the growth-monitoring collector now and re-run this '
    'script once at least a week of samples has accumulated. In the '
    'meantime, use 05_write_rate_projection_proxy.sql in this same '
    'directory, which derives a cruder estimate from insert counters and '
    'average row width without needing any history at all.'       AS notice;
\endif
