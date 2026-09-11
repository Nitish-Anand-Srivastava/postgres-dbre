/*
===============================================================================
SCRIPT NAME:
03_write_volume_and_hot_ratio.sql

PURPOSE:
Measures the table's write volume and HOT update ratio, which determine the ongoing cost of the new index.

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
Step 03 of workflow 'schema-changes/add-index-large-table'

RELATED SCRIPTS:
04_target_table_size.sql

HOW TO INTERPRET RESULTS:
This is the cost side of the decision and it is routinely skipped. An index is not a one-off build cost; on a table taking millions of inserts a day it is millions of additional index entries written, WAL-logged, shipped to every Aurora reader, and vacuumed every single day for as long as the index exists. Find your target table and read total_row_writes: that number multiplied by the index's per-entry cost is what you are signing up for permanently. Then read pct_hot_updates -- if it is already low, the new index will make it lower, because a HOT update requires that no indexed column changed. On an update-heavy table, adding an index on a column that changes is one of the most expensive things you can do to the write path.
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
