/*
===============================================================================
SCRIPT NAME:
02_force_ssl_parameter_status.sql

PURPOSE:
Checks whether the Aurora rds.force_ssl parameter is currently enabled on this instance, which is the authoritative server-side SSL enforcement mechanism.

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
Step 02 of workflow 'security-and-access/ssl-and-connection-security'

RELATED SCRIPTS:
03_enabling_force_ssl.md

HOW TO INTERPRET RESULTS:
setting = '1' (or 'on', depending on engine version's boolean rendering) means the server itself refuses unencrypted connections; setting = '0'/'off' means enforcement is left entirely to each client's own sslmode configuration -- see 03_enabling_force_ssl.md to change this.
===============================================================================
*/

-- rds.force_ssl is an Aurora/RDS-specific parameter surfaced as an ordinary
-- row in pg_settings on instances where it is defined; it does not exist as
-- a GUC on self-managed PostgreSQL at all, so this is guarded rather than
-- assumed present.
SELECT EXISTS (
    SELECT 1 FROM pg_settings WHERE name = 'rds.force_ssl'
)                                                                AS rds_force_ssl_defined
\gset

\if :rds_force_ssl_defined
SELECT name, setting, context, source
FROM pg_settings
WHERE name = 'rds.force_ssl';
\else
SELECT
    'rds.force_ssl is not defined on this instance -- this is expected on '
    'self-managed/non-RDS PostgreSQL, and would be unexpected on an Aurora '
    'instance. If this is genuinely an Aurora PostgreSQL instance, confirm '
    'you are connected to the instance you intend to check.'               AS notice;
\endif
