/*
===============================================================================
SCRIPT NAME:
01_workload_by_application_and_session_age.sql

PURPOSE:
Attributes the current workload to each service and shows when its sessions were established, making the newly deployed fleet visible.

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
Step 01 of workflow 'incident-response/post-deployment-incident'

RELATED SCRIPTS:
02_migration_lock_waits.sql

HOW TO INTERPRET RESULTS:
Look for a group whose newest_session_started (and often oldest_session_started) matches the deployment timestamp: that is the new fleet. Compare its blocked_count, active_count and longest_active_query against the services that did not change -- the difference is the effect of the release, isolated in one query.
===============================================================================
*/

-- Current workload attributed to the service that generated it, including
-- when each group's sessions were established. After a deployment this is the
-- fastest way to watch the new fleet arrive: a cluster of sessions whose
-- newest_session_started (and often oldest_session_started) lines up with the
-- rollout timestamp is the newly deployed replica set, and comparing its
-- active_count / blocked_count against the services that did NOT change tells
-- you within seconds whether the deployment is the cause or a victim.
--
-- This depends on every service actually setting application_name; a large
-- '(unset)' group makes the attribution useless, so fix that in the affected
-- service's connection string as a follow-up action.
SELECT
    coalesce(NULLIF(a.application_name, ''), '(unset)')          AS application_name,
    a.usename,
    a.datname,
    count(*)                                                     AS session_count,
    count(*) FILTER (WHERE a.state = 'active')                   AS active_count,
    count(*) FILTER (WHERE a.state = 'idle')                     AS idle_count,
    count(*) FILTER (WHERE a.state = 'idle in transaction')      AS idle_in_txn_count,
    count(*) FILTER (WHERE cardinality(pg_blocking_pids(a.pid)) > 0) AS blocked_count,
    min(a.backend_start)                                         AS oldest_session_started,
    max(a.backend_start)                                         AS newest_session_started,
    max(now() - a.query_start) FILTER (WHERE a.state = 'active') AS longest_active_query,
    max(now() - a.xact_start)                                    AS longest_open_transaction
FROM pg_stat_activity a
WHERE a.pid <> pg_backend_pid()
  AND a.backend_type = 'client backend'
GROUP BY 1, 2, 3
ORDER BY session_count DESC;
