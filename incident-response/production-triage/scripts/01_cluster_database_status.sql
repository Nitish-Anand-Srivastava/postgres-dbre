/*
===============================================================================
SCRIPT NAME:
01_cluster_database_status.sql

PURPOSE:
Step 1 of 10: confirms whether this connection is on the writer or a reader, and reports Aurora's cluster-wide instance status and lag.

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
Step 01 of workflow 'incident-response/production-triage'

RELATED SCRIPTS:
02_active_sessions.sql

HOW TO INTERPRET RESULTS:
Run this first, always. If you are not on the instance you believe you are on, every later result describes the wrong machine. A writer that reports itself as a reader means a failover happened or DNS is stale -- stop the checklist and go to the failover investigation. Replica lag rising on every reader at once points at writer saturation rather than at the readers.
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

-- Aurora detection by catalog lookup only. This never calls the
-- Aurora-specific function unless that function actually exists, so the
-- script is safe to run unchanged on community PostgreSQL too.
SELECT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'aurora_replica_status') AS is_aurora
\gset

\if :is_aurora
-- Aurora-specific cluster-wide replica status and lag, callable from any
-- instance in the cluster (writer or reader). This is the correct,
-- Aurora-native way to check reader lag -- it reflects the actual Aurora
-- storage-layer replication mechanism, not standard PostgreSQL streaming
-- replication. The exact column set has evolved across Aurora PostgreSQL
-- engine releases, so this script selects all columns explicitly via
-- information_schema-free SELECT * (a documented, deliberate exception to
-- the "no bare SELECT *" rule, since the function's return type is
-- engine-version-defined rather than a fixed catalog): confirm the columns
-- returned in your environment with \x and adjust downstream automation
-- accordingly.
SELECT *
FROM aurora_replica_status()
ORDER BY 1;
\else
SELECT 'aurora_replica_status() is not present on this server, so this is not an Aurora PostgreSQL cluster. Use pg_stat_replication on the primary instead to review replication status for this topology.' AS notice;
\endif
