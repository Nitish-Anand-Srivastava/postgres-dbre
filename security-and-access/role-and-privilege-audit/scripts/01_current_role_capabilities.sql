/*
===============================================================================
SCRIPT NAME:
01_current_role_capabilities.sql

PURPOSE:
Confirms what the currently connected auditing role itself can do -- its super/create/replication attributes and its own group memberships -- as context for interpreting the rest of the audit.

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
Step 01 of workflow 'security-and-access/role-and-privilege-audit'

RELATED SCRIPTS:
02_all_roles_and_memberships.sql

HOW TO INTERPRET RESULTS:
rolsuper should read false on Aurora for every role, including this one; member_of_roles shows which group roles this auditing session itself belongs to, which determines what the remaining queries in this workflow will actually be able to see.
===============================================================================
*/

-- What the currently connected role can actually do: superuser-equivalent
-- Aurora role membership, and the built-in monitoring roles that grant
-- read access to statistics views without needing broader privileges. On
-- Aurora/RDS, the true "superuser" is reserved for AWS-managed processes;
-- the bootstrap application user is typically only a member of
-- rds_superuser, which is intentionally weaker (no filesystem/OS access).
SELECT
    r.rolname,
    r.rolsuper,
    r.rolcreaterole,
    r.rolcreatedb,
    r.rolreplication,
    r.rolbypassrls,
    ARRAY(
        SELECT b.rolname
        FROM pg_auth_members m
        JOIN pg_roles b ON b.oid = m.roleid
        WHERE m.member = r.oid
    )                                                            AS member_of_roles
FROM pg_roles r
WHERE r.rolname = current_user;
