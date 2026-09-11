/*
===============================================================================
SCRIPT NAME:
02_replication_lag_sql_companion.sql

PURPOSE:
Aurora-native cluster-wide replica status and lag, the SQL-side companion to the AuroraReplicaLag CloudWatch metric.

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
Step 02 of workflow 'observability/cloudwatch'

RELATED SCRIPTS:
03_cloudwatch_metric_to_sql_mapping.md, ../../replication-and-ha/replication-lag/README.md

HOW TO INTERPRET RESULTS:
This is the correct SQL-side companion to AuroraReplicaLag -- pg_stat_replication will not show Aurora readers at all (see the Aurora notes). Run this from any instance in the cluster; it does not need to be the writer. A reader whose lag here is elevated should show the same elevation in its CloudWatch AuroraReplicaLag graph -- if the two disagree substantially, suspect a metric collection delay before suspecting the query.
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
