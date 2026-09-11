/*
===============================================================================
SCRIPT NAME:
03_write_volume_by_table.sql

PURPOSE:
Measures inserts, updates, deletes, and the HOT update ratio per table to distinguish append-only growth from update churn.

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
Step 03 of workflow 'storage-and-capacity/table-growth'

RELATED SCRIPTS:
04_dead_tuples_ranked.sql

HOW TO INTERPRET RESULTS:
This is the decisive script. High n_tup_ins with negligible updates and deletes is clean append-only growth: partitioning and retention are the only levers, and vacuum tuning will not help. High n_tup_upd with pct_hot_updates well below 50% is the expensive case -- every update rewrites the row and every index entry for it, so look for an index on the column being updated (status, updated_at) and consider dropping it or lowering fillfactor. Always check stats_reset before drawing conclusions: an Aurora failover zeroes these counters, so a low number may mean a recent failover rather than a quiet table.
===============================================================================
*/

-- Row-level write volume per table since the last statistics reset. This is
-- the single best in-database proxy for "which tables are actually driving
-- storage and WAL growth", because every insert, every non-HOT update
-- (which writes a whole new row version plus every index entry), and every
-- delete (which leaves a dead tuple until vacuum reclaims it) contributes
-- directly to both.
--
-- Counters are cumulative since the last reset; pg_stat_all_tables has no
-- stats_reset column of its own, so read stats_reset from pg_stat_database
-- for the current database to know what window these numbers cover.
\set top_n 30
SELECT
    schemaname                                                  AS schema_name,
    relname                                                     AS table_name,
    n_tup_ins,
    n_tup_upd,
    n_tup_del,
    n_tup_hot_upd,
    n_tup_ins + n_tup_upd + n_tup_del                            AS total_row_writes,
    round(100.0 * n_tup_hot_upd / NULLIF(n_tup_upd, 0), 1)        AS pct_hot_updates,
    n_live_tup,
    n_dead_tup,
    pg_size_pretty(pg_total_relation_size(relid))                 AS total_size,
    (SELECT stats_reset FROM pg_stat_database
      WHERE datname = current_database())                        AS stats_reset
FROM pg_stat_all_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY (n_tup_ins + n_tup_upd + n_tup_del) DESC
LIMIT :top_n;
