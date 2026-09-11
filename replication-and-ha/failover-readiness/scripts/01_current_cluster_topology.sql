/*
===============================================================================
SCRIPT NAME:
01_current_cluster_topology.sql

PURPOSE:
Confirms current writer/reader role for the connection being tested, to be run against each endpoint your applications actually use.

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
Step 01 of workflow 'replication-and-ha/failover-readiness'

RELATED SCRIPTS:
../../disaster-recovery/cluster-failover-drill/README.md

HOW TO INTERPRET RESULTS:
Run this against the writer/cluster endpoint AND the reader endpoint your applications use; confirm each resolves to the role you expect. If an application's configured endpoint resolves to a specific instance rather than a cluster/reader endpoint, this is a readiness gap.
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
