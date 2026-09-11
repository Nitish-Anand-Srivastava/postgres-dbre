/*
===============================================================================
SCRIPT NAME:
01_identify_database_load.sql

PURPOSE:
Cluster-wide session/state overview to establish overall load before drilling in.

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
Step 01 of workflow 'performance/high-cpu'

RELATED SCRIPTS:
02_identify_active_queries.sql

HOW TO INTERPRET RESULTS:
A high 'active' session_count with NULL wait_event is the strongest indicator of genuine CPU-bound load. Compare against normal baseline session counts for this time of day.
===============================================================================
*/

-- Snapshot of every backend known to this instance right now, grouped by
-- high-level state. Run this first on any performance or availability
-- investigation to understand overall load before drilling into detail.
SELECT
    datname,
    state,
    wait_event_type,
    count(*)                                                   AS session_count,
    count(*) FILTER (WHERE state = 'active')                   AS active_count,
    max(now() - query_start)                                   AS longest_query_runtime,
    max(now() - xact_start)                                    AS longest_txn_runtime
FROM pg_stat_activity
WHERE pid <> pg_backend_pid()
GROUP BY datname, state, wait_event_type
ORDER BY session_count DESC, longest_query_runtime DESC NULLS LAST;
