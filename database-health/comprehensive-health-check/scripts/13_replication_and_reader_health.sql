/*
===============================================================================
SCRIPT NAME:
13_replication_and_reader_health.sql

PURPOSE:
Reports Aurora cluster replica status and lag from the Aurora-native status function.

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
Step 13 of workflow 'database-health/comprehensive-health-check'

RELATED SCRIPTS:
../../replication-and-ha/replication-health/README.md

HOW TO INTERPRET RESULTS:
Reader lag directly determines how stale a balance or order-history read served from a reader can be. Sub-second lag is the normal Aurora profile; sustained lag above a few seconds means read-your-own-write assumptions in the application are being violated, which on an exchange surfaces as users seeing a deposit credited and then apparently disappearing. If this function is unavailable you are not on Aurora -- use replication-and-ha/replication-health for the standard streaming-replication equivalent.
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
