/*
===============================================================================
SCRIPT NAME:
03_session_outcome_counters.sql

PURPOSE:
Checks how sessions are actually ending, which separates server-side cancellation from client-side abandonment.

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
Step 03 of workflow 'incident-response/application-timeouts'

RELATED SCRIPTS:
04_blocking_and_waits.sql

HOW TO INTERPRET RESULTS:
Rising sessions_abandoned means clients are giving up and disconnecting -- a client-side deadline, not a server-side timeout. Rising sessions_fatal means the server is ending them. A high pct_rollback alongside either suggests transactions are failing rather than completing, which is worth correlating with the application's error taxonomy.
===============================================================================
*/

-- Per-database session outcome counters (PostgreSQL 14+, present on Aurora
-- PostgreSQL 17). These are cumulative since stats_reset, so read them as
-- "has this been happening at all", then re-run a minute later and diff the
-- values to get a rate:
--   * sessions_abandoned -- the client vanished without a clean disconnect
--     (application crash, pod eviction, network partition, or a load balancer
--     cutting an established connection on its idle timeout).
--   * sessions_fatal     -- the server ended the session with a FATAL error
--     (out of connection slots, authentication failure, backend crash).
--   * sessions_killed    -- the session was ended by an administrator command,
--     i.e. somebody has already run a termination during this incident.
-- Movement in sessions_killed that you cannot account for means another
-- responder is acting on the same cluster: find them before you both act.
SELECT
    datname,
    numbackends,
    sessions,
    sessions_abandoned,
    sessions_fatal,
    sessions_killed,
    xact_commit,
    xact_rollback,
    deadlocks,
    round(100.0 * sessions_abandoned / NULLIF(sessions, 0), 2)   AS pct_sessions_abandoned,
    round(100.0 * xact_rollback / NULLIF(xact_commit + xact_rollback, 0), 2) AS pct_rollback,
    stats_reset
FROM pg_stat_database
WHERE datname IS NOT NULL
ORDER BY sessions_abandoned DESC NULLS LAST;
