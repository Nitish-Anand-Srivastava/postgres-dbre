/*
===============================================================================
SCRIPT NAME:
05_vacuum_and_xid_status.sql

PURPOSE:
Checks autovacuum activity and transaction ID age for a regression caused by an interrupted vacuum.

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
Step 05 of workflow 'database-health/post-maintenance-check'

RELATED SCRIPTS:
06_settings_and_extension_verification.sql, ../../vacuum-and-autovacuum/vacuum-progress/README.md

HOW TO INTERPRET RESULTS:
Compare pct_of_freeze_max_age against the pre-maintenance-check reading. If it did not improve, or is now higher, despite this maintenance including a restart that could have interrupted an in-flight anti-wraparound autovacuum (see pre-maintenance-check script 05), confirm autovacuum has resumed and is actively progressing on the affected table.
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

-- Transaction ID (XID) age per database, measured against datfrozenxid.
-- autovacuum_freeze_max_age (default 200,000,000) is the point at which
-- autovacuum is forced to run in every table regardless of cost limits;
-- autovacuum_vacuum_freeze_min_age / vacuum_failsafe_age (default
-- 1,600,000,000) is the emergency threshold before wraparound-protection
-- kicks in and PostgreSQL refuses new writes to protect data integrity.
SELECT
    datname,
    age(datfrozenxid)                                           AS xid_age,
    datfrozenxid,
    round(
        100.0 * age(datfrozenxid) /
        (SELECT setting::numeric FROM pg_settings WHERE name = 'autovacuum_freeze_max_age'),
        2
    )                                                            AS pct_of_freeze_max_age,
    2147483647 - age(datfrozenxid)                                AS xids_remaining_to_wraparound
FROM pg_database
WHERE datallowconn
ORDER BY xid_age DESC;
