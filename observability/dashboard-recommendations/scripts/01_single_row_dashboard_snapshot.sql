/*
===============================================================================
SCRIPT NAME:
01_single_row_dashboard_snapshot.sql

PURPOSE:
Single-row, dashboard-panel-friendly snapshot of the handful of metrics most teams put on a 'cluster at a glance' stat panel.

AURORA POSTGRESQL VERSION:
Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise)

EXECUTION LOCATION:
Writer instance preferred; safe to run on a reader but results reflect only that reader's local activity

SAFETY:
READ ONLY

EXPECTED IMPACT:
Minimal -- reads system catalogs/statistics views only, no table locks beyond a brief catalog lookup.

REQUIRED PRIVILEGES:
Role membership in `pg_monitor` (or `pg_read_all_stats`) is sufficient. No superuser required.

PREREQUISITES:
None beyond CONNECT on the target database.

EXECUTION ORDER:
Step 01 of workflow 'observability/dashboard-recommendations'

RELATED SCRIPTS:
02_baseline_dashboard_layout_recommendations.md

HOW TO INTERPRET RESULTS:
Wire each column into its own stat panel, or the whole row into a single table panel, as a quick-start dashboard while the fuller per-signal panels from postgres-metrics/cloudwatch/wait-event-analysis are being built out individually. worst_pct_of_freeze_max_age and longest_open_txn are the two values most worth an alert threshold immediately, since both indicate slow-moving conditions that are easy to miss without a standing panel.
===============================================================================
*/

-- Single-row, dashboard-panel-friendly snapshot combining the handful of
-- metrics most teams put on a "cluster at a glance" Grafana stat panel.
-- Point a scheduled collector (or a Grafana PostgreSQL data source panel
-- set to table/stat visualization) at this query directly -- it
-- deliberately returns exactly one row so it renders cleanly without any
-- client-side aggregation.
SELECT
    now()                                                                      AS captured_at,
    (SELECT count(*) FROM pg_stat_activity)                                    AS current_connections,
    round(
        100.0 * (SELECT count(*) FROM pg_stat_activity) /
        NULLIF((SELECT setting::numeric FROM pg_settings WHERE name = 'max_connections'), 0),
        2
    )                                                                          AS pct_connections_used,
    (SELECT count(*) FROM pg_stat_activity WHERE state = 'idle in transaction') AS idle_in_transaction_count,
    (SELECT max(now() - xact_start) FROM pg_stat_activity WHERE xact_start IS NOT NULL) AS longest_open_txn,
    round(
        100.0 * sum(blks_hit) / NULLIF(sum(blks_hit) + sum(blks_read), 0), 2
    )                                                                          AS cache_hit_pct,
    sum(deadlocks)                                                             AS deadlocks_since_reset,
    (SELECT round(max(100.0 * age(datfrozenxid) /
         (SELECT setting::numeric FROM pg_settings WHERE name = 'autovacuum_freeze_max_age')), 2)
     FROM pg_database WHERE datallowconn)                                      AS worst_pct_of_freeze_max_age
FROM pg_stat_database
WHERE datname IS NOT NULL;
