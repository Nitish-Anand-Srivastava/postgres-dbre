/*
===============================================================================
SCRIPT NAME:
05_replication_slot_backpressure.sql

PURPOSE:
Checks replication slot WAL retention, since a stalled logical replication consumer can backpressure the writer.

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
Step 05 of workflow 'performance/throughput-degradation'

RELATED SCRIPTS:
../../replication-and-ha/replication-health/README.md

HOW TO INTERPRET RESULTS:
A slot with active=false and a large/growing retained WAL size means a consumer has stopped reading; this can eventually force storage growth and, in extreme cases, operational intervention to drop the slot.
===============================================================================
*/

-- Combines replication slot lag with current WAL position to flag slots
-- that are retaining an unusually large amount of WAL. On Aurora, WAL
-- retained by an inactive or lagging logical replication slot still
-- consumes storage on the cluster volume and can eventually force
-- corrective action (dropping the slot) if the consumer cannot be
-- recovered.
--
-- IMPORTANT (verified against Aurora PostgreSQL 17.7): pg_current_wal_lsn()
-- errors on Aurora clusters running with wal_level=replica (Aurora's
-- default) -- Aurora's current-WAL-position tracking for this family of
-- functions depends on the same logical-WAL-cache infrastructure used by
-- logical replication, and is only reliably callable once
-- wal_level=logical is set. current_setting('wal_level') is a plain GUC
-- read that never fails, so it is used here as a guard: a CASE expression
-- only evaluates the branch matching its WHEN condition (the same
-- documented mechanism used to avoid division-by-zero in a CASE), so
-- pg_current_wal_lsn() is never actually invoked unless wal_level is
-- already 'logical'. The current position is computed once in a CTE and
-- reused, so the guard only needs to be evaluated a single time per query.
\set retained_wal_warning_gb 50
-- NOTE: the threshold is cast to numeric BEFORE multiplying by 1024^3.
-- pg_wal_lsn_diff() returns numeric, but the psql-substituted literal
-- ":retained_wal_warning_gb" is a bare integer constant; PostgreSQL infers
-- an int4 literal type for "50 * 1024 * 1024 * 1024" left-to-right before
-- ever comparing it against the numeric LSN diff, and that intermediate
-- product (~53.7 billion) overflows int4 (max ~2.1 billion), raising
-- "integer out of range" -- casting the threshold to numeric first forces
-- numeric arithmetic throughout and avoids the overflow entirely.
WITH current_position AS (
    SELECT CASE WHEN current_setting('wal_level') = 'logical'
                THEN pg_current_wal_lsn()
                ELSE NULL
           END AS lsn
)
SELECT
    s.slot_name,
    s.slot_type,
    s.active,
    s.wal_status,
    CASE WHEN c.lsn IS NOT NULL
         THEN pg_size_pretty(pg_wal_lsn_diff(c.lsn, s.restart_lsn))
         ELSE 'NOT AVAILABLE (wal_level=' || current_setting('wal_level') || ', requires logical on Aurora)'
    END                                                             AS retained_wal,
    CASE WHEN c.lsn IS NOT NULL
         THEN pg_wal_lsn_diff(c.lsn, s.restart_lsn) >
              (:retained_wal_warning_gb::numeric * 1024 * 1024 * 1024)
         ELSE NULL
    END                                                             AS exceeds_warning_threshold
FROM pg_replication_slots s
CROSS JOIN current_position c
ORDER BY (CASE WHEN c.lsn IS NOT NULL THEN pg_wal_lsn_diff(c.lsn, s.restart_lsn) ELSE NULL END) DESC NULLS LAST;
