/*
===============================================================================
SCRIPT NAME:
01_confirm_recovery_role_and_uptime.sql

PURPOSE:
Confirms this instance's current writer/reader role and how recently it started, to verify a failover occurred.

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
Step 01 of workflow 'performance/performance-after-failover'

RELATED SCRIPTS:
02_cache_warmup_progress.sql

HOW TO INTERPRET RESULTS:
A very recent pg_postmaster_start_time combined with this instance now reporting as the writer strongly confirms a recent promotion/failover.
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

SELECT pg_postmaster_start_time() AS instance_start_time,
       now() - pg_postmaster_start_time() AS instance_uptime;
