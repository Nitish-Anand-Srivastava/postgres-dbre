/*
===============================================================================
SCRIPT NAME:
06_aurora_replica_topology_and_lag.sql

PURPOSE:
Reports every instance in the Aurora cluster (writer and readers) along
with current replica lag, active transaction count, and last update time,
using Aurora's native replica status function rather than community
PostgreSQL's pg_stat_replication (which does not reflect Aurora's storage-
level replication model).

AURORA POSTGRESQL VERSION:
17+ (aurora_replica_status() is Aurora-specific)

EXECUTION LOCATION:
Any instance (writer or reader) -- aurora_replica_status() returns
cluster-wide topology information regardless of which instance you query
from.

SAFETY:
READ ONLY

EXPECTED IMPACT:
None -- reads Aurora's internally maintained replica status, not
application data.

REQUIRED PRIVILEGES:
None beyond CONNECT on the target database.

PREREQUISITES:
None. Returns a single row (the writer) on a single-instance cluster.

EXECUTION ORDER:
Step 06 of common/scripts

RELATED SCRIPTS:
05_instance_recovery_and_role_status.sql

HOW TO INTERPRET RESULTS:
`session_id = 'MASTER_SESSION_ID'` identifies the writer's own row; every
other row is a reader instance. `replica_lag_in_msec` is Aurora's native
lag measurement for that reader; per AWS documentation,
`last_update_timestamp` is NULL for the row matching the instance you are
currently connected to (this is expected, not a fault). Sustained high
`replica_lag_in_msec` on a specific reader, especially combined with a
high `active_txns` count on that reader, points toward that reader being
overloaded rather than a cluster-wide replication problem -- see
replication-and-ha/reader-lag-investigation/ (once populated) for the
full workflow.
===============================================================================
*/

SELECT
    server_id                        AS instance_identifier,
    session_id                       AS session_identifier,
    durable_lsn                      AS durable_lsn,
    current_read_lsn                 AS current_read_lsn,
    replica_lag_in_msec              AS replica_lag_ms,
    active_txns                      AS active_transaction_count,
    last_update_timestamp            AS last_update_timestamp
FROM aurora_replica_status()
ORDER BY (session_id = 'MASTER_SESSION_ID') DESC, replica_lag_in_msec DESC NULLS LAST;
