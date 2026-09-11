/*
===============================================================================
SCRIPT NAME:
04_replication_lag_baseline.sql

PURPOSE:
Records the current Aurora reader lag as the pre-maintenance baseline.

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
Step 04 of workflow 'database-health/pre-maintenance-check'

RELATED SCRIPTS:
05_vacuum_and_xid_status.sql, ../../replication-and-ha/replication-lag/README.md

HOW TO INTERPRET RESULTS:
Save this output verbatim -- post-maintenance-check compares against it. Starting an operation while lag is already elevated means the brief additional replication disruption the operation causes stacks on top of an already-degraded baseline, extending the time before reads served from readers are trustworthy again.
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
