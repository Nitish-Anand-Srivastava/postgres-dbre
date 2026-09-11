/*
===============================================================================
SCRIPT NAME:
01_instance_identity_and_uptime.sql

PURPOSE:
Establishes which instance, engine version, and role this session is connected to, and how long the instance has been up.

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
Step 01 of workflow 'database-health/comprehensive-health-check'

RELATED SCRIPTS:
02_database_and_table_sizes.sql

HOW TO INTERPRET RESULTS:
An instance_uptime of less than a few hours means a reboot or failover occurred recently: treat this run as a new baseline, because all cumulative counters restarted then. If is_reader_instance is true, do not draw writer-wide conclusions from the connection, lock, or transaction steps -- reconnect to the cluster writer endpoint for those.
===============================================================================
*/

-- Context for everything that follows. Two facts matter most before
-- reading any other health metric:
--   1. Writer or reader? pg_stat_activity, pg_locks and most statistics
--      counters are per-instance, so a reader shows only its own sessions.
--   2. How long has this instance been up? Every cumulative counter in
--      this workflow accumulates since the instance started or since the
--      last pg_stat_reset(); a recent Aurora failover silently resets them
--      and makes comparison against a previous health check invalid.
--
-- aurora_version() only exists on Aurora PostgreSQL. Its presence is
-- detected through pg_proc first so this script also runs unmodified on
-- community PostgreSQL 17 (for example, in a local staging environment)
-- instead of failing with "function does not exist".
SELECT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'aurora_version') AS is_aurora_engine
\gset

SELECT
    current_database()                                          AS database_name,
    current_user                                                AS connected_as,
    inet_server_addr()                                          AS server_address,
    inet_server_port()                                          AS server_port,
    version()                                                   AS postgresql_version,
    pg_is_in_recovery()                                         AS is_reader_instance,
    pg_postmaster_start_time()                                  AS instance_started_at,
    now() - pg_postmaster_start_time()                          AS instance_uptime,
    current_setting('timezone')                                 AS server_timezone,
    now()                                                       AS health_check_captured_at;

\if :is_aurora_engine
SELECT aurora_version()                                         AS aurora_engine_version;
\else
SELECT 'aurora_version() is not available on this server, so this is community '
       'PostgreSQL (or a non-Aurora managed service) rather than Aurora '
       'PostgreSQL. Every script in this workflow still runs, but the '
       'Aurora-specific reader-lag step will report that aurora_replica_status() '
       'is unavailable.'                                        AS notice;
\endif
