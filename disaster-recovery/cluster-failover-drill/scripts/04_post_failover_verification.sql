/*
===============================================================================
SCRIPT NAME:
04_post_failover_verification.sql

PURPOSE:
Confirms the new writer's identity and how recently it started, run against the cluster/writer endpoint immediately after the drill to verify the promotion completed as expected.

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
Step 04 of workflow 'disaster-recovery/cluster-failover-drill'

RELATED SCRIPTS:
../../database-health/post-maintenance-check/README.md

HOW TO INTERPRET RESULTS:
is_reader_instance should read false (this is now the writer) and instance_start_time should be very recent, consistent with the drill's promotion having just completed. Follow up with database-health/post-maintenance-check for the fuller post-event verification, and performance/performance-after-failover if buffer-cache warm-up impact is observed.
===============================================================================
*/

-- Run against the cluster (writer) endpoint immediately after the drill.
-- A very recent instance_start_time here, combined with pg_is_in_recovery()
-- = false, confirms this connection is now reaching the newly promoted
-- writer.
SELECT
    pg_is_in_recovery()                                          AS is_reader_instance,
    pg_postmaster_start_time()                                   AS instance_start_time,
    now() - pg_postmaster_start_time()                           AS instance_uptime;
