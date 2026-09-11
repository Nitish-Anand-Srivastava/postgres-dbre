/*
===============================================================================
SCRIPT NAME:
04_autovacuum_contribution.sql

PURPOSE:
Checks whether concurrent autovacuum workers are a meaningful contributor to current load.

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
Step 04 of workflow 'performance/high-database-load'

RELATED SCRIPTS:
../../vacuum-and-autovacuum/autovacuum-not-keeping-up/README.md

HOW TO INTERPRET RESULTS:
Multiple simultaneous autovacuum workers on large tables during peak hours can materially add to load; this is not a bug, but may need cost-limit tuning to spread the work off-peak.
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
