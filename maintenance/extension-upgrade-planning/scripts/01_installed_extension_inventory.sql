/*
===============================================================================
SCRIPT NAME:
01_installed_extension_inventory.sql

PURPOSE:
Baseline inventory of every extension currently installed and its active version, the starting point for upgrade planning.

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
Step 01 of workflow 'maintenance/extension-upgrade-planning'

RELATED SCRIPTS:
02_extension_version_skew_check.sql

HOW TO INTERPRET RESULTS:
This is the same inventory used by routine-maintenance-checklist -- use it here specifically as the baseline for the version-skew comparison in the next script.
===============================================================================
*/

-- Extensions currently installed in this database vs. what Aurora
-- PostgreSQL makes available. Many investigation scripts in this toolkit
-- depend on pg_stat_statements (query stats) and/or pgstattuple (exact
-- bloat); confirm both are available/installed before relying on those
-- scripts.
SELECT
    e.extname,
    e.extversion,
    n.nspname                                                   AS installed_schema
FROM pg_extension e
JOIN pg_namespace n ON n.oid = e.extnamespace
ORDER BY e.extname;
