/*
===============================================================================
SCRIPT NAME:
02_sessions_outside_expected_access_model.sql

PURPOSE:
Classifies every live session against a configurable list of expected roles and an expected client network range, so sessions inconsistent with the documented access model sort to the top.

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
Step 02 of workflow 'security-and-access/access-anomaly-investigation'

RELATED SCRIPTS:
03_privilege_escalation_surface.sql

HOW TO INTERPRET RESULTS:
A row with role_not_expected = true AND source_outside_expected_cidr = true is the highest-priority finding in this workflow: an unrecognized identity from an unrecognized network. Either flag alone still needs an explanation -- an expected role from an unexpected address usually means a leaked credential, while an unexpected role from the expected address usually means an undocumented internal tool. local_or_internal_connection = true (NULL client_addr) is characteristic of Aurora-internal activity rather than an application and should be set aside, not chased first. Note that these variables encode *your* documented model, so a clean result only means 'consistent with what was configured here', not 'safe'.
===============================================================================
*/

-- Classifies live sessions against the documented access model instead of
-- asking an engineer to spot the odd one by eye during an incident. Set the
-- two variables below from your own access documentation before running:
-- the defaults are illustrative role names and an RFC1918 application-tier
-- range, and leaving them unchanged will simply flag everything.
\set expected_roles 'app_readwrite,app_readonly,reporting_ro'
\set expected_client_cidr '10.0.0.0/8'

SELECT
    a.pid,
    a.usename                                                    AS role_name,
    a.client_addr,
    coalesce(nullif(a.application_name, ''), '(not set)')        AS application_name,
    a.state,
    a.backend_start,
    NOT (a.usename = ANY (string_to_array(:'expected_roles', ',')))  AS role_not_expected,
    CASE
        WHEN a.client_addr IS NULL THEN NULL
        ELSE NOT (a.client_addr << :'expected_client_cidr'::inet)
    END                                                          AS source_outside_expected_cidr,
    a.client_addr IS NULL                                        AS local_or_internal_connection
FROM pg_stat_activity a
WHERE a.pid <> pg_backend_pid()
  AND a.backend_type = 'client backend'
ORDER BY
    (NOT (a.usename = ANY (string_to_array(:'expected_roles', ',')))) DESC,
    (a.client_addr IS NOT NULL
        AND NOT (a.client_addr << :'expected_client_cidr'::inet)) DESC,
    a.backend_start;
