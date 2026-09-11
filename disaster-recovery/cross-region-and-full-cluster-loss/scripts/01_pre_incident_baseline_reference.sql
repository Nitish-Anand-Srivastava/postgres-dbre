/*
===============================================================================
SCRIPT NAME:
01_pre_incident_baseline_reference.sql

PURPOSE:
Captures a lightweight baseline (engine version, current database, and connection role) intended to be kept on file for comparison after a cross-region recovery, run periodically as part of standing DR preparedness rather than during the event itself.

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
Step 01 of workflow 'disaster-recovery/cross-region-and-full-cluster-loss'

RELATED SCRIPTS:
02_cross_region_and_full_loss_runbook.md

HOW TO INTERPRET RESULTS:
Keep this output on file (alongside your DR runbook, not only in the database itself, since the whole point is to have it available even if the source cluster/region is unavailable). After a cross-region recovery, re-run this same query against the recovered cluster and confirm the engine version and database inventory match what you expect before directing production traffic to it.
===============================================================================
*/

-- Is this instance currently a writer or a reader? On Aurora, every reader
-- instance is always in continuous recovery mode (pg_is_in_recovery() =
-- true), even though it is not a traditional PostgreSQL physical standby --
-- it is replaying redo log records shipped from the shared Aurora storage
-- layer, not a WAL stream from the writer. Always confirm this before
-- interpreting any other replication-related query on this connection.
SELECT
    pg_is_in_recovery()                                          AS is_reader_instance,
    CASE WHEN pg_is_in_recovery()
         THEN 'This connection is to an Aurora reader instance (or a standard PostgreSQL physical replica).'
         ELSE 'This connection is to the Aurora writer instance (or a standalone/primary PostgreSQL server).'
    END                                                           AS role_description;

-- Engine-version and database-inventory baseline, kept alongside the
-- cluster_recovery_role() output above as a pre-incident reference point --
-- useful for confirming a cross-region-recovered cluster (which may have
-- been restored from an older snapshot copy) matches the expected engine
-- version and database set before cutting application traffic over to it.
SELECT
    current_setting('server_version')                            AS server_version,
    current_setting('server_version_num')                        AS server_version_num,
    (SELECT array_agg(datname ORDER BY datname)
       FROM pg_database
      WHERE datistemplate = false)                                AS user_databases;
