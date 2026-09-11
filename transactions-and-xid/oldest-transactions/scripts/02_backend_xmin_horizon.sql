/*
===============================================================================
SCRIPT NAME:
02_backend_xmin_horizon.sql

PURPOSE:
Shows each backend's reported xmin, the actual value that determines the vacuum cleanup horizon (distinct from xact_start wall-clock age).

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
Step 02 of workflow 'transactions-and-xid/oldest-transactions'

RELATED SCRIPTS:
../../concurrency-and-locking/long-running-transactions/README.md

HOW TO INTERPRET RESULTS:
Sort by xmin_age, not xact_wall_clock_age -- a session can have a short wall-clock lifetime but, if it started during high transaction throughput, still hold a comparatively old xmin.
===============================================================================
*/

-- Backend xmin horizon: the oldest xmin currently held by any backend
-- determines how far back vacuum can safely clean up dead tuples,
-- independent of how long (in wall-clock time) that backend's transaction
-- has been open.
SELECT
    pid,
    datname,
    usename,
    state,
    backend_xmin,
    age(backend_xmin)                                            AS xmin_age,
    now() - xact_start                                            AS xact_wall_clock_age
FROM pg_stat_activity
WHERE backend_xmin IS NOT NULL
ORDER BY age(backend_xmin) DESC;
