/*
===============================================================================
SCRIPT NAME:
07_dead_tuples_and_vacuum_status.sql

PURPOSE:
Ranks tables by dead tuple volume and shows when each was last vacuumed or analyzed.

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
Step 07 of workflow 'database-health/comprehensive-health-check'

RELATED SCRIPTS:
08_autovacuum_activity.sql, ../../vacuum-and-autovacuum/dead-tuples/README.md

HOW TO INTERPRET RESULTS:
Read dead_tuple_pct together with last_autovacuum. A high percentage with a recent autovacuum means autovacuum is running but losing ground against write volume (a tuning problem). A high percentage with a stale or NULL last_autovacuum means autovacuum is not reaching the table at all (a blocked-vacuum or worker-starvation problem). High churn on order status transitions and balance updates makes orders, wallets, and open_positions the usual occupants of the top of this list.
===============================================================================
*/

-- Tables ranked by dead tuple ratio and absolute dead tuple count. High
-- dead-tuple ratios combined with a stale last_autovacuum timestamp are the
-- clearest sign that autovacuum is not keeping up with a table's write rate.
\set top_n 30
SELECT
    schemaname                                                  AS schema_name,
    relname                                                     AS table_name,
    n_live_tup,
    n_dead_tup,
    round(100.0 * n_dead_tup / NULLIF(n_live_tup + n_dead_tup, 0), 2) AS dead_tuple_pct,
    last_vacuum,
    last_autovacuum,
    last_analyze,
    last_autoanalyze,
    autovacuum_count,
    vacuum_count
FROM pg_stat_all_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY n_dead_tup DESC
LIMIT :top_n;
