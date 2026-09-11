/*
===============================================================================
SCRIPT NAME:
08_environment_summary.sql

PURPOSE:
Produces a single-row "where and who am I" summary (database, role,
backend PID, server address/port, postmaster start time, config reload
time) intended as the very first query run in any new session before an
investigation begins.

AURORA POSTGRESQL VERSION:
17+

EXECUTION LOCATION:
Any instance (writer or reader)

SAFETY:
READ ONLY

EXPECTED IMPACT:
None -- reads session and instance metadata only.

REQUIRED PRIVILEGES:
None beyond CONNECT on the target database. Every function used here is
unrestricted (readable by any authenticated role).

PREREQUISITES:
None.

EXECUTION ORDER:
Step 08 of common/scripts (or step 00 -- run first, alongside script 01,
when opening a brand-new session)

RELATED SCRIPTS:
01_postgres_and_aurora_version.sql
05_instance_recovery_and_role_status.sql

HOW TO INTERPRET RESULTS:
`backend_pid` is this session's own PID -- useful to exclude yourself
(`pid <> pg_backend_pid()`) when later querying pg_stat_activity.
`postmaster_start_time` tells you how long the current instance process
has been running (a recent value can indicate a recent restart, reboot,
or failover-driven promotion). `config_last_loaded` tells you when
`pg_reload_conf()` was last effective; if it is older than an expected
parameter change, that change may still be `PENDING_REBOOT` rather than
live.
===============================================================================
*/

SELECT
    current_database()                AS connected_database,
    current_user                      AS connected_role,
    pg_backend_pid()                  AS backend_pid,
    inet_server_addr()                AS server_address,
    inet_server_port()                AS server_port,
    pg_postmaster_start_time()        AS postmaster_start_time,
    pg_conf_load_time()                AS config_last_loaded,
    clock_timestamp() AT TIME ZONE 'UTC' AS check_time_utc;
