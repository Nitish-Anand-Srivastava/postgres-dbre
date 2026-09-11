/*
===============================================================================
SCRIPT NAME:
05_replication_lag_baseline.sql

PURPOSE:
Records the current Aurora reader lag as the pre-deployment baseline.

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
Step 05 of workflow 'database-health/pre-deployment-check'

RELATED SCRIPTS:
06_maintenance_in_flight.sql, ../../replication-and-ha/replication-lag/README.md

HOW TO INTERPRET RESULTS:
Record these values verbatim: post-deployment-check compares against them. Starting a deployment while lag is already elevated means the migration's additional WAL will push reader staleness past the point where balance and order-history reads served from readers become visibly wrong to users.
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
