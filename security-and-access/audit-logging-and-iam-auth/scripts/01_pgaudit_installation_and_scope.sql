/*
===============================================================================
SCRIPT NAME:
01_pgaudit_installation_and_scope.sql

PURPOSE:
Checks whether the pgaudit extension is installed and, if so, reports its current logging-scope configuration.

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
Step 01 of workflow 'security-and-access/audit-logging-and-iam-auth'

RELATED SCRIPTS:
02_iam_authenticated_roles.sql

HOW TO INTERPRET RESULTS:
If installed, pgaudit.log determines what gets logged (e.g. 'read, write, role' vs. a narrower scope) -- compare the configured scope against your actual compliance requirement rather than assuming any nonempty configuration is sufficient. If not installed, treat this as a gap to close only if a specific compliance requirement needs it -- installing it is not free (added logging volume and overhead) and should be a deliberate decision.
===============================================================================
*/

-- pgaudit must be explicitly installed (shared_preload_libraries entry plus
-- CREATE EXTENSION) -- this script never installs it itself, it only
-- reports current status, and prints an instructional notice instead if it
-- is absent.
SELECT EXISTS (
    SELECT 1 FROM pg_extension WHERE extname = 'pgaudit'
)                                                                AS pgaudit_installed
\gset

\if :pgaudit_installed
SELECT extversion AS pgaudit_version
FROM pg_extension
WHERE extname = 'pgaudit';

SELECT name, setting, context, source
FROM pg_settings
WHERE name LIKE 'pgaudit.%'
ORDER BY name;
\else
SELECT
    'pgaudit is not installed in this database. This script never runs '
    'CREATE EXTENSION automatically (installation is a change-managed, '
    'reboot-driving shared_preload_libraries change) -- see '
    '03_installing_pgaudit_and_granting_iam_auth.md for the guarded '
    'installation runbook if object-level audit logging is required.'      AS notice;
\endif
