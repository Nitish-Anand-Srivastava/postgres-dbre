/*
===============================================================================
SCRIPT NAME:
02_all_roles_and_memberships.sql

PURPOSE:
Enumerates every non-system role in the cluster along with its login/create/replication attributes and its full group-membership list.

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
Step 02 of workflow 'security-and-access/role-and-privilege-audit'

RELATED SCRIPTS:
03_object_level_grants_by_schema.sql

HOW TO INTERPRET RESULTS:
rolsuper = true anywhere in this result is an immediate finding on Aurora (see this workflow's escalation criteria). Cross-reference member_of_roles against a documented role-design diagram; any membership you cannot explain is the actual audit finding, not a false positive to dismiss.
===============================================================================
*/

-- Every role in the cluster (excluding the internal pg_* predefined roles,
-- which are fixed PostgreSQL built-ins, not cluster-specific grants) with
-- its key attributes and the group roles it is a member of.
SELECT
    r.rolname,
    r.rolcanlogin,
    r.rolsuper,
    r.rolcreaterole,
    r.rolcreatedb,
    r.rolreplication,
    r.rolbypassrls,
    r.rolvaliduntil,
    ARRAY(
        SELECT b.rolname
        FROM pg_auth_members m
        JOIN pg_roles b ON b.oid = m.roleid
        WHERE m.member = r.oid
        ORDER BY 1
    )                                                            AS member_of_roles
FROM pg_roles r
WHERE r.rolname NOT LIKE 'pg\_%'
ORDER BY r.rolname;
