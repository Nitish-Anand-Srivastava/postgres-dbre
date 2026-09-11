/*
===============================================================================
SCRIPT NAME:
02_current_role_and_privileges.sql

PURPOSE:
Reports the current session's role attributes and membership in the
predefined roles that gate access to most investigation workflows in this
repository (pg_monitor, pg_read_all_stats, pg_read_all_settings,
pg_signal_backend, rds_superuser).

AURORA POSTGRESQL VERSION:
17+ (rds_superuser is an Aurora/RDS-specific role; the rest are standard
PostgreSQL predefined roles also present on Aurora)

EXECUTION LOCATION:
Any instance (writer or reader)

SAFETY:
READ ONLY

EXPECTED IMPACT:
Minimal -- reads pg_roles and evaluates pg_has_role() for the current
session's role only.

REQUIRED PRIVILEGES:
None beyond CONNECT on the target database. Every role queried here is
readable by any authenticated role for its own membership check.

PREREQUISITES:
None.

EXECUTION ORDER:
Step 02 of common/scripts (recommended after confirming version in script 01)

RELATED SCRIPTS:
01_postgres_and_aurora_version.sql

HOW TO INTERPRET RESULTS:
If `is_member_of_pg_monitor` is false, most READ ONLY scripts in this
repository that depend on pg_stat_activity.query text for other users'
sessions, or on pg_settings visibility, will return incomplete results
(rows with nulled-out sensitive columns) rather than failing outright --
treat unexpectedly sparse investigation output as a permissions gap, not
a clean bill of health. `has_rolsuper_attribute` should be false on Aurora;
if it is unexpectedly true, verify you are connected to the intended
Aurora cluster and not a self-managed PostgreSQL instance.
===============================================================================
*/

SELECT
    current_user                                                       AS current_role_name,
    session_user                                                        AS session_role_name,
    r.rolsuper                                                          AS has_rolsuper_attribute,
    r.rolcreaterole                                                     AS has_createrole_attribute,
    r.rolcreatedb                                                       AS has_createdb_attribute,
    pg_has_role(current_user, 'pg_monitor', 'MEMBER')                   AS is_member_of_pg_monitor,
    pg_has_role(current_user, 'pg_read_all_stats', 'MEMBER')            AS is_member_of_pg_read_all_stats,
    pg_has_role(current_user, 'pg_read_all_settings', 'MEMBER')         AS is_member_of_pg_read_all_settings,
    pg_has_role(current_user, 'pg_signal_backend', 'MEMBER')            AS is_member_of_pg_signal_backend,
    pg_has_role(current_user, 'rds_superuser', 'MEMBER')                AS is_member_of_rds_superuser
FROM pg_roles r
WHERE r.rolname = current_user;
