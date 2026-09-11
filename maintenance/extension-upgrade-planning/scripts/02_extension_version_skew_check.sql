/*
===============================================================================
SCRIPT NAME:
02_extension_version_skew_check.sql

PURPOSE:
Compares each installed extension's active version against the newest version available on this Aurora engine release.

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
Step 02 of workflow 'maintenance/extension-upgrade-planning'

RELATED SCRIPTS:
03_extension_upgrade_runbook.md

HOW TO INTERPRET RESULTS:
upgrade_available = true identifies a candidate; before applying, look up the specific version jump's release notes (or the extension's CHANGELOG) to classify it as a routine patch bump vs. a larger jump worth testing first -- see 03_extension_upgrade_runbook.md.
===============================================================================
*/

-- Flags any installed extension with a newer version available on this
-- specific Aurora engine release. The comparison itself is a plain text
-- max() over pg_available_extension_versions.version, which is a reasonable
-- first pass but can misorder multi-digit version segments (e.g. '1.9' vs
-- '1.10') -- always look at the actual version list for anything but a
-- quick triage.
SELECT
    e.extname,
    e.extversion                                                AS installed_version,
    (SELECT max(v.version)
       FROM pg_available_extension_versions v
      WHERE v.name = e.extname)                                 AS latest_available_version,
    e.extversion <> (SELECT max(v.version)
                        FROM pg_available_extension_versions v
                       WHERE v.name = e.extname)                 AS upgrade_available
FROM pg_extension e
ORDER BY upgrade_available DESC, e.extname;
