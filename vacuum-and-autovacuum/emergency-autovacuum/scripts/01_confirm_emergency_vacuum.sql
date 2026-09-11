/*
===============================================================================
SCRIPT NAME:
01_confirm_emergency_vacuum.sql

PURPOSE:
Confirms whether a currently running vacuum is in anti-wraparound/failsafe mode by cross-referencing its target table's age against the configured thresholds.

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
Step 01 of workflow 'vacuum-and-autovacuum/emergency-autovacuum'

RELATED SCRIPTS:
../../transactions-and-xid/xid-wraparound-risk/scripts/04_current_autovacuum_activity.sql

HOW TO INTERPRET RESULTS:
A worker present here for a table whose age already exceeds autovacuum_freeze_max_age (from the xid-wraparound-risk scripts) is running in anti-wraparound mode -- let it complete.
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

-- Cross-reference each relid above against transactions-and-xid/xid-wraparound-risk/scripts/01_database_transaction_age.sql and 02_table_transaction_age.sql output: a worker on a table already past autovacuum_freeze_max_age is running in mandatory anti-wraparound mode.
