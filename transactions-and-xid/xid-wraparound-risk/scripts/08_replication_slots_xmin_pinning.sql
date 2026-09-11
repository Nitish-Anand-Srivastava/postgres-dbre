/*
===============================================================================
SCRIPT NAME:
08_replication_slots_xmin_pinning.sql

PURPOSE:
Checks replication slots for a retained xmin/catalog_xmin that could be pinning the vacuum cleanup horizon.

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
Step 08 of workflow 'transactions-and-xid/xid-wraparound-risk'

RELATED SCRIPTS:
../../replication-and-ha/replication-health/README.md

HOW TO INTERPRET RESULTS:
An inactive slot (active = false) with a very old xmin is a common, easily missed cause of a database-wide vacuum horizon stall -- confirm whether the consuming service still exists before dropping the slot.
===============================================================================
*/

-- Physical and logical replication slots, and whether they are actively
-- consumed. An inactive slot with a growing (restart_lsn falling behind
-- current WAL) footprint will hold WAL on disk indefinitely and, on Aurora,
-- can contribute to storage growth and volume I/O -- this is one of the
-- most common causes of unexplained storage growth on Aurora clusters that
-- use logical replication or CDC (e.g. Debezium, DMS).
SELECT
    slot_name,
    slot_type,
    plugin,
    database,
    active,
    active_pid,
    wal_status,
    restart_lsn,
    confirmed_flush_lsn,
    pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)            AS retained_wal_bytes
FROM pg_replication_slots
ORDER BY retained_wal_bytes DESC NULLS LAST;
