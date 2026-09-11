/*
===============================================================================
SCRIPT NAME:
05_replication_slot_wal_retention.sql

PURPOSE:
Flags replication slots retaining an unusually large amount of WAL relative to a documented threshold.

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
Step 05 of workflow 'database-health/capacity-health-check'

RELATED SCRIPTS:
06_temp_file_and_index_footprint.sql, ../../replication-and-ha/replication-lag/README.md

HOW TO INTERPRET RESULTS:
Any slot with exceeds_warning_threshold = true is consuming cluster storage right now with no offsetting benefit if its consumer is gone or broken -- this is storage growth that a table-size inventory never shows. Confirm each slot has an active, healthy consumer (a CDC pipeline, a logical replica) before concluding it is safe to leave in place.
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
