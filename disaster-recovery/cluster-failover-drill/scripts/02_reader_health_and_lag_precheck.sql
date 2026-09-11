/*
===============================================================================
SCRIPT NAME:
02_reader_health_and_lag_precheck.sql

PURPOSE:
Confirms every reader's replication lag is low immediately before triggering the drill, so the drill measures the failover mechanism itself rather than a pre-existing lag problem.

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
Step 02 of workflow 'disaster-recovery/cluster-failover-drill'

RELATED SCRIPTS:
03_failover_drill_runbook.md

HOW TO INTERPRET RESULTS:
Every reader should show low, stable lag before proceeding. If the reader you intend to promote (or any reader) shows elevated lag, either wait for it to stabilize or explicitly target a healthy reader via --target-db-instance-identifier in the drill runbook -- do not proceed against a reader you have not confirmed healthy.
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
