/*
===============================================================================
SCRIPT NAME:
01_current_engine_version_inventory.sql

PURPOSE:
Records the exact community and Aurora engine version this cluster is running, as the documented before-state for the upgrade.

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
Step 01 of workflow 'maintenance/minor-version-upgrade-readiness'

RELATED SCRIPTS:
02_upgrade_blockers_precheck.sql

HOW TO INTERPRET RESULTS:
Save this output verbatim in the change ticket before the window opens, and re-run it immediately afterward: the pair of before/after results is the only in-database proof the upgrade actually applied. Note that an Aurora patch-level upgrade can change aurora_engine_version while leaving server_version unchanged -- comparing only the community version can make a real upgrade look like a no-op.
===============================================================================
*/

-- Community PostgreSQL version identity. server_version_num is the reliable
-- machine-comparable form (e.g. 170007 for 17.7); the version() string also
-- records the build/platform details.
SELECT
    current_setting('server_version')                            AS server_version,
    current_setting('server_version_num')                        AS server_version_num,
    version()                                                    AS full_version_string;

-- Aurora exposes an additional, Aurora-specific engine build identifier via
-- aurora_version(). It does not exist on community PostgreSQL, so detect it
-- from the catalog first rather than calling it unconditionally (a bare call
-- would fail with "function aurora_version() does not exist" on any
-- non-Aurora instance, including a local test database).
SELECT EXISTS (
    SELECT 1 FROM pg_proc WHERE proname = 'aurora_version'
)                                                                AS is_aurora
\gset

\if :is_aurora
SELECT aurora_version()                                          AS aurora_engine_version;
\else
SELECT 'aurora_version() is not present on this server, so this is community PostgreSQL rather than Aurora PostgreSQL. The community version reported above is the only engine identity available here.' AS notice;
\endif
