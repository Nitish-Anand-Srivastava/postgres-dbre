/*
===============================================================================
SCRIPT NAME:
01_postgres_and_aurora_version.sql

PURPOSE:
Reports the PostgreSQL and Aurora engine version currently in use, so
every subsequent investigation step is interpreted against the correct
version's behavior and catalog columns.

AURORA POSTGRESQL VERSION:
17+ (aurora_version() is an Aurora-specific function; this script must run
against an Aurora PostgreSQL instance, not community PostgreSQL)

EXECUTION LOCATION:
Any instance (writer or reader)

SAFETY:
READ ONLY

EXPECTED IMPACT:
None -- reads server-reported version strings only.

REQUIRED PRIVILEGES:
None beyond CONNECT on the target database. No special role required.

PREREQUISITES:
None.

EXECUTION ORDER:
Step 01 of common/scripts (recommended first step of any investigation)

RELATED SCRIPTS:
02_current_role_and_privileges.sql

HOW TO INTERPRET RESULTS:
`server_version_num` is the numeric PostgreSQL version (e.g. 170004 for
17.4); compare it against the version assumptions documented in each
workflow's script headers. `aurora_engine_version` identifies the Aurora
PostgreSQL engine release. If this script errors with
"function aurora_version() does not exist", you are not connected to an
Aurora PostgreSQL instance -- stop and confirm the connection target
before trusting any Aurora-specific guidance elsewhere in this repository.
===============================================================================
*/

SELECT
    version()                                    AS postgres_full_version_string,
    current_setting('server_version_num')::int   AS server_version_num,
    aurora_version()                              AS aurora_engine_version;
