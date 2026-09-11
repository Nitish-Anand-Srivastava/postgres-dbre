/*
===============================================================================
SCRIPT NAME:
05_instance_recovery_and_role_status.sql

PURPOSE:
Confirms whether the instance you are currently connected to is the
cluster writer or a reader, and identifies which Aurora instance that is,
so subsequent investigation steps are known to be running against the
intended target.

AURORA POSTGRESQL VERSION:
17+ (aurora_db_instance_identifier() is Aurora-specific)

EXECUTION LOCATION:
Any instance (writer or reader) -- this script is specifically meant to
identify which one you are on.

SAFETY:
READ ONLY

EXPECTED IMPACT:
None -- reads in-memory recovery/session state only.

REQUIRED PRIVILEGES:
None beyond CONNECT on the target database.

PREREQUISITES:
None.

EXECUTION ORDER:
Step 05 of common/scripts (run whenever endpoint routing is ambiguous, or
before comparing writer vs. reader behavior)

RELATED SCRIPTS:
06_aurora_replica_topology_and_lag.sql

HOW TO INTERPRET RESULTS:
`is_reader_instance = true` (equivalently `instance_role = 'reader'`)
means writes will fail against this session; if you intended to run a
write or DDL script and see this, you are connected to the wrong
endpoint/instance. Always cross-check `aurora_instance_identifier` against
the instance identifier shown in the RDS/Aurora console when an
investigation depends on targeting one specific instance (e.g. comparing
two readers with different latency).
===============================================================================
*/

SELECT
    pg_is_in_recovery()                                    AS is_reader_instance,
    CASE WHEN pg_is_in_recovery() THEN 'reader' ELSE 'writer' END
                                                            AS instance_role,
    aurora_db_instance_identifier()                        AS aurora_instance_identifier,
    clock_timestamp() AT TIME ZONE 'UTC'                   AS check_time_utc;
