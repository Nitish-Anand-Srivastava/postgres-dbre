/*
===============================================================================
SCRIPT NAME:
05_replication_slot_retention.sql

PURPOSE:
Checks replication slots for retained WAL and pinned xmin -- the cause that worsens fastest if left alone.

AURORA POSTGRESQL VERSION:
Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise)

EXECUTION LOCATION:
Writer instance only (the query reads/writes state that only exists or is meaningful on the writer)

SAFETY:
READ ONLY

EXPECTED IMPACT:
Minimal -- reads system catalogs/statistics views only, no table locks beyond a brief catalog lookup.

REQUIRED PRIVILEGES:
Role membership in `pg_monitor` (or `pg_read_all_stats`) is sufficient. No superuser required.

PREREQUISITES:
None beyond CONNECT on the target database.

EXECUTION ORDER:
Step 05 of workflow 'storage-and-capacity/unexpected-storage-growth'

RELATED SCRIPTS:
06_temp_file_and_local_storage.sql

HOW TO INTERPRET RESULTS:
A slot with active = false and large retained_wal is an abandoned consumer pinning storage indefinitely, and a logical slot additionally pins the xmin horizon, which explains dead tuples that will not clear no matter what you do to autovacuum. A wal_status of 'lost' means required WAL has already been removed and the consumer cannot resume without a full resynchronization -- at that point the slot is providing nothing and is pure cost. Confirm with the owning team before dropping any slot: on an exchange these usually feed a data warehouse, a compliance archive, or an AWS DMS pipeline, and forcing a resynchronization is a bigger event than the storage it frees. Aurora's own readers never appear here.
===============================================================================
*/

-- Combines replication slot lag with current WAL position to flag slots
-- that are retaining an unusually large amount of WAL. On Aurora, WAL
-- retained by an inactive or lagging logical replication slot still
-- consumes storage on the cluster volume and can eventually force
-- corrective action (dropping the slot) if the consumer cannot be
-- recovered.
\set retained_wal_warning_gb 50
-- NOTE: the threshold is cast to numeric BEFORE multiplying by 1024^3.
-- pg_wal_lsn_diff() returns numeric, but the psql-substituted literal
-- ":retained_wal_warning_gb" is a bare integer constant; PostgreSQL infers
-- an int4 literal type for "50 * 1024 * 1024 * 1024" left-to-right before
-- ever comparing it against the numeric LSN diff, and that intermediate
-- product (~53.7 billion) overflows int4 (max ~2.1 billion), raising
-- "integer out of range" -- casting the threshold to numeric first forces
-- numeric arithmetic throughout and avoids the overflow entirely.
SELECT
    slot_name,
    slot_type,
    active,
    wal_status,
    pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS retained_wal,
    pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) >
        (:retained_wal_warning_gb::numeric * 1024 * 1024 * 1024)    AS exceeds_warning_threshold
FROM pg_replication_slots
ORDER BY pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) DESC;
