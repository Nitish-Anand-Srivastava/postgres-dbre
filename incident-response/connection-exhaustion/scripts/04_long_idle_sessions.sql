/*
===============================================================================
SCRIPT NAME:
04_long_idle_sessions.sql

PURPOSE:
Lists plain idle sessions ranked by idle duration -- the cheapest and safest slots to reclaim.

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
Step 04 of workflow 'incident-response/connection-exhaustion'

RELATED SCRIPTS:
05_idle_in_transaction_sessions.sql

HOW TO INTERPRET RESULTS:
An idle session holds no locks, no snapshot and no in-flight work, so reclaiming it costs a healthy client one reconnect. Connection_age spanning days alongside a long idle_duration is a leak; ages clustered in the last few minutes are a deployment or restart storm instead.
===============================================================================
*/

-- Plain 'idle' sessions (connected, but NOT inside a transaction) ranked by
-- how long they have been idle. These are the cheapest connection slots to
-- reclaim during connection exhaustion: an idle session holds no locks, no
-- snapshot and no in-flight work, so ending it loses nothing except the TCP
-- connection itself, which a healthy pool re-establishes transparently.
--
-- Contrast with 'idle in transaction' sessions (see the dedicated script in
-- this workflow): those DO hold a snapshot and possibly locks, and ending one
-- rolls back whatever its transaction had already done.
\set top_n 50
SELECT
    pid,
    datname,
    usename,
    coalesce(NULLIF(application_name, ''), '(unset)')            AS application_name,
    client_addr,
    backend_start,
    state_change,
    now() - state_change                                         AS idle_duration,
    now() - backend_start                                        AS connection_age,
    left(query, 120)                                             AS last_statement
FROM pg_stat_activity
WHERE state = 'idle'
  AND pid <> pg_backend_pid()
ORDER BY idle_duration DESC
LIMIT :top_n;
