/*
===============================================================================
SCRIPT NAME:
02_replication_lag_after_maintenance.sql

PURPOSE:
Re-checks Aurora reader lag for direct comparison against the pre-maintenance baseline.

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
Step 02 of workflow 'database-health/post-maintenance-check'

RELATED SCRIPTS:
03_connection_recovery_check.sql, ../pre-maintenance-check/README.md

HOW TO INTERPRET RESULTS:
Compare directly against pre-maintenance-check script 04. A brief lag spike immediately after the restart is expected as the reader catches up on redo; the finding is lag that has not converged back toward baseline within a few minutes, which points to a reader under-provisioned for the current WAL generation rate.
===============================================================================
*/

-- Aurora-specific cluster-wide replica status and lag, callable from any
-- instance in the cluster (writer or reader). This is the correct,
-- Aurora-native way to check reader lag -- it reflects the actual Aurora
-- storage-layer replication mechanism, not standard PostgreSQL streaming
-- replication. The exact column set has evolved across Aurora PostgreSQL
-- engine releases, so this script selects all columns explicitly via
-- information_schema-free SELECT * (a documented, deliberate exception to
-- the "no bare SELECT *" rule, since the function's return type is
-- engine-version-defined rather than a fixed catalog): confirm the columns
-- returned in your environment with \x and adjust downstream automation
-- accordingly.
SELECT *
FROM aurora_replica_status()
ORDER BY 1;
