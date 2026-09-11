/*
===============================================================================
SCRIPT NAME:
01_instance_identity_and_uptime.sql

PURPOSE:
Confirms the database is reachable at all, and identifies exactly which instance answered, its role, and how long it has been running.

AURORA POSTGRESQL VERSION:
Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise)

EXECUTION LOCATION:
Any instance (writer or reader)

SAFETY:
READ ONLY

EXPECTED IMPACT:
Minimal -- reads system catalogs/statistics views only, no table locks beyond a brief catalog lookup.

REQUIRED PRIVILEGES:
CONNECT on the target database. No elevated privileges required.

PREREQUISITES:
None beyond CONNECT on the target database.

EXECUTION ORDER:
Step 01 of workflow 'incident-response/database-unavailable'

RELATED SCRIPTS:
02_cluster_role_and_replica_status.sql

HOW TO INTERPRET RESULTS:
A returned row proves the postmaster is up and serving queries -- announce that immediately. Then compare instance_uptime against the incident start: a shorter uptime means a restart or failover already happened, and is_reader_instance = true when you expected a writer means the endpoint resolved to the wrong instance.
===============================================================================
*/

-- "What am I actually connected to, and has it restarted?" -- the first
-- question of any availability incident. If this query returns a row at all,
-- the postmaster is up, listening, authenticating and serving queries, which
-- immediately rules out a large class of reported-as-database outages (DNS,
-- security group, endpoint misrouting, expired credentials, or an
-- application-side connection pool that is broken on its own).
--
-- instance_uptime is the highest-value column: an uptime shorter than the
-- reported incident duration means the instance restarted, or a failover
-- promoted a different writer, during the incident window -- which changes
-- the entire investigation.
SELECT
    current_database()                                          AS connected_database,
    current_user                                                AS connected_role,
    inet_server_addr()                                          AS server_address,
    inet_server_port()                                          AS server_port,
    pg_is_in_recovery()                                         AS is_reader_instance,
    pg_postmaster_start_time()                                  AS instance_start_time,
    now() - pg_postmaster_start_time()                          AS instance_uptime,
    now()                                                       AS server_time_now,
    current_setting('server_version')                           AS server_version;
