/*
===============================================================================
SCRIPT NAME:
05_write_volume_by_table.sql

PURPOSE:
Attributes write volume to individual tables, which is the reliable WAL proxy on Aurora where the WAL statistics view is unavailable.

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
Step 05 of workflow 'storage-and-capacity/wal-generation'

RELATED SCRIPTS:
../table-growth/README.md

HOW TO INTERPRET RESULTS:
This is the most dependable attribution available on Aurora. Rank by total_row_writes to find the tables driving redo volume, then read pct_hot_updates on the update-heavy ones: a low HOT ratio means every update is rewriting the row plus an entry in every index, which is pure, addressable WAL amplification. Cross-reference the offending table against its index count -- dropping one unnecessary index on a table taking millions of updates removes a WAL entry from every one of them. Always check stats_reset first; an Aurora failover zeroes these counters and makes a busy table look idle.
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
