/*
===============================================================================
SCRIPT NAME:
01_current_sessions_by_identity_and_origin.sql

PURPOSE:
Captures the live session inventory -- role, client address, application, transport encryption, state, and age -- as the first evidence step of an access investigation.

AURORA POSTGRESQL VERSION:
Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise)

EXECUTION LOCATION:
Any instance (writer or reader)

SAFETY:
READ ONLY

EXPECTED IMPACT:
Minimal -- reads system catalogs/statistics views only, no table locks beyond a brief catalog lookup.

REQUIRED PRIVILEGES:
Role membership in `pg_monitor` (or `pg_read_all_stats`) is sufficient. No superuser required. Without `pg_monitor` (or `pg_read_all_stats`), `pg_stat_activity` masks query text and several identity columns for sessions belonging to other roles, which will under-report the anomaly rather than error.

PREREQUISITES:
None beyond CONNECT on the target database.

EXECUTION ORDER:
Step 01 of workflow 'security-and-access/access-anomaly-investigation'

RELATED SCRIPTS:
02_sessions_outside_expected_access_model.sql

HOW TO INTERPRET RESULTS:
Read this as an inventory to be explained, row by row: every distinct combination of role_name, client_addr, and application_name should map to a known service, job, or person. Long session_age on a session from an unexpected address is more concerning than a short one -- it has had time to read a great deal. ssl_in_use = false on any session outside the documented internal path means the traffic was also readable on the network. Save this output with its capture time before proceeding; script 04's containment steps destroy it.
===============================================================================
*/

-- Live session inventory, joined to pg_stat_ssl so transport encryption is
-- visible per session. This is a snapshot: the rows disappear when the
-- sessions end, so capture the output into the incident record before doing
-- anything else. Requires pg_monitor to see other roles' details -- without
-- it, most columns for other users are NULL and the picture is misleading
-- rather than merely incomplete.
SELECT
    a.pid,
    a.usename                                                    AS role_name,
    a.datname                                                    AS database_name,
    a.client_addr,
    a.client_hostname,
    a.client_port,
    coalesce(nullif(a.application_name, ''), '(not set)')        AS application_name,
    a.backend_type,
    a.state,
    s.ssl                                                        AS ssl_in_use,
    s.version                                                    AS tls_version,
    a.backend_start,
    now() - a.backend_start                                      AS session_age,
    now() - a.state_change                                       AS time_in_current_state,
    left(coalesce(a.query, ''), 200)                             AS current_or_last_query
FROM pg_stat_activity a
LEFT JOIN pg_stat_ssl s ON s.pid = a.pid
WHERE a.pid <> pg_backend_pid()
ORDER BY a.client_addr NULLS LAST, a.backend_start;
