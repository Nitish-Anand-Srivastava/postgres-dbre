/*
===============================================================================
SCRIPT NAME:
01_candidate_roles_by_activity_and_ownership.sql

PURPOSE:
Ranks every non-system role by current connection count, objects owned, and group-membership purpose, surfacing the roles with the least evidence of ongoing legitimate use first.

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
Step 01 of workflow 'security-and-access/unused-and-orphaned-roles'

RELATED SCRIPTS:
02_role_cleanup_runbook.md

HOW TO INTERPRET RESULTS:
Focus on rows where is_rds_builtin_role = false, current_connections = 0, objects_owned = 0, and has_members_count = 0 -- these have no current connection, own nothing, and are not serving as a group role for anyone else. Confirm against your service/employee inventory (this snapshot cannot see infrequent, e.g. monthly, legitimate connections) before treating any of them as safe to remove.
===============================================================================
*/

-- Cross-references role attributes against current connections and object
-- ownership to surface roles with no visible current activity. Results are
-- ordered with the least-evidence-of-use roles first; this is a starting
-- point for investigation, not an automatic deletion list -- pg_stat_activity
-- reflects only right-now connections, not historical usage.
SELECT
    r.rolname,
    r.rolcanlogin,
    r.rolname LIKE 'rds\_%'                                     AS is_rds_builtin_role,
    (SELECT count(*) FROM pg_stat_activity a
      WHERE a.usename = r.rolname)                               AS current_connections,
    (SELECT count(*) FROM pg_class c
      WHERE c.relowner = r.oid)                                  AS objects_owned,
    (SELECT count(*) FROM pg_auth_members m
      WHERE m.roleid = r.oid)                                    AS has_members_count,
    (SELECT count(*) FROM pg_auth_members m2
      WHERE m2.member = r.oid)                                   AS member_of_count
FROM pg_roles r
WHERE r.rolname NOT LIKE 'pg\_%'
ORDER BY is_rds_builtin_role ASC, current_connections ASC, objects_owned ASC, has_members_count ASC, r.rolname;
