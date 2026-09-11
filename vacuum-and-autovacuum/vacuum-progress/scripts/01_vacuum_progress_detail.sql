/*
===============================================================================
SCRIPT NAME:
01_vacuum_progress_detail.sql

PURPOSE:
Shows detailed progress for every currently running VACUUM (manual or autovacuum), using PostgreSQL 17's byte-based progress columns.

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
Step 01 of workflow 'vacuum-and-autovacuum/vacuum-progress'

RELATED SCRIPTS:
02_relation_scan_rate.sql

HOW TO INTERPRET RESULTS:
Re-run this every 30-60 seconds; heap_blks_scanned and indexes_processed should both be advancing over time. dead_tuple_bytes approaching max_dead_tuple_bytes signals an index vacuum cycle is about to be triggered (normal).
===============================================================================
*/

-- Autovacuum (and manual VACUUM/ANALYZE) workers currently running, and
-- what phase they are in via pg_stat_progress_vacuum. On PG17 the dead
-- tuple counters are reported in bytes (max_dead_tuple_bytes /
-- dead_tuple_bytes), not tuple counts, reflecting the new TID-store based
-- vacuum implementation.
SELECT
    a.pid,
    a.datname,
    n.nspname                                                    AS schema_name,
    c.relname                                                    AS relation_name,
    v.phase,
    v.heap_blks_total,
    v.heap_blks_scanned,
    round(100.0 * v.heap_blks_scanned / NULLIF(v.heap_blks_total, 0), 2) AS pct_heap_scanned,
    v.indexes_total,
    v.indexes_processed,
    pg_size_pretty(v.dead_tuple_bytes)                            AS dead_tuple_data_collected,
    pg_size_pretty(v.max_dead_tuple_bytes)                        AS dead_tuple_data_limit,
    now() - a.xact_start                                          AS running_for
FROM pg_stat_progress_vacuum v
JOIN pg_stat_activity a ON a.pid = v.pid
LEFT JOIN pg_class c ON c.oid = v.relid
LEFT JOIN pg_namespace n ON n.oid = c.relnamespace
ORDER BY running_for DESC;
