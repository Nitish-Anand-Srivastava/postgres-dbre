/*
===============================================================================
SCRIPT NAME:
02_standard_streaming_replication.sql

PURPOSE:
Checks standard PostgreSQL streaming replication status from the writer, for any external physical/logical replica or CDC consumer (NOT Aurora readers).

AURORA POSTGRESQL VERSION:
Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise)

EXECUTION LOCATION:
Writer instance only (the query reads/writes state that only exists or is meaningful on the writer)

SAFETY:
READ ONLY

EXPECTED IMPACT:
Minimal -- reads system catalogs/statistics views only, no table locks beyond a brief catalog lookup.

REQUIRED PRIVILEGES:
Role membership in `pg_monitor` (or `pg_read_all_stats`) is sufficient. No superuser required.

PREREQUISITES:
None beyond CONNECT on the target database.

EXECUTION ORDER:
Step 02 of workflow 'replication-and-ha/replication-lag'

RELATED SCRIPTS:
03_writer_wal_generation.sql

HOW TO INTERPRET RESULTS:
An empty result here is completely normal on Aurora even with healthy readers -- it only shows genuine external streaming consumers. Do not interpret an empty result as 'no replicas exist'.
===============================================================================
*/

-- Standard PostgreSQL streaming replication status, as seen from the writer.
-- IMPORTANT (Aurora-specific): this view only shows genuine WAL-streaming
-- consumers -- e.g. a logical replication subscriber, an external physical
-- replica, or AWS DMS -- connected to this instance. It does NOT show
-- Aurora's own reader instances, because Aurora readers do not attach as
-- standard streaming replicas; they read redo records from the shared
-- Aurora storage volume through an internal mechanism that is invisible to
-- pg_stat_replication. Use aurora_replica_status() (writer or reader) or
-- the AWS Console/CloudWatch AuroraReplicaLag metric to observe Aurora
-- reader lag; never assume an empty pg_stat_replication result means "no
-- replicas" on Aurora.
SELECT
    pid,
    usename,
    application_name,
    client_addr,
    state,
    sync_state,
    write_lag,
    flush_lag,
    replay_lag
FROM pg_stat_replication
ORDER BY replay_lag DESC NULLS LAST;
