/*
===============================================================================
SCRIPT NAME:
02_policy_definitions_and_bypass_roles.sql

PURPOSE:
Prints the actual USING/WITH CHECK expression of every policy in the database, then lists every role that bypasses RLS entirely.

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
Step 02 of workflow 'security-and-access/row-level-security-review'

RELATED SCRIPTS:
03_rls_coverage_for_sensitive_table.sql

HOW TO INTERPRET RESULTS:
Read using_expression literally: `true`, or an expression that does not reference any session/tenant context, means the policy admits every row for the roles it applies to. applies_to_command = 'SELECT' only means write paths are unrestricted -- a role could insert ledger rows attributed to a customer it cannot read. In the second result set, every login-capable role with rolbypassrls = true is a standing, total exemption from all of the policies above; the expected steady-state size of that list is zero.
===============================================================================
*/

-- Actual policy definitions. A non-zero policy count means nothing on its
-- own -- what matters is the qual (the USING expression applied to rows the
-- statement reads) and with_check (applied to rows it writes). A policy with
-- qual = 'true' restricts nothing.
SELECT
    schemaname                                                   AS schema_name,
    tablename                                                    AS table_name,
    policyname                                                   AS policy_name,
    permissive,
    roles                                                        AS applies_to_roles,
    cmd                                                          AS applies_to_command,
    qual                                                         AS using_expression,
    with_check                                                   AS with_check_expression
FROM pg_policies
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY schema_name, table_name, policy_name;

-- Roles that bypass row-level security outright. rolbypassrls is a role
-- attribute, not a grant, so it does not appear in any object's ACL and is
-- easy to miss in an object-centric privilege audit. rds_superuser members
-- are listed alongside it because they can set the attribute on themselves.
SELECT
    r.rolname                                                    AS role_name,
    r.rolcanlogin,
    r.rolbypassrls,
    r.rolsuper,
    EXISTS (
        SELECT 1
        FROM pg_auth_members m
        JOIN pg_roles g ON g.oid = m.roleid
        WHERE m.member = r.oid
          AND g.rolname = 'rds_superuser'
    )                                                            AS is_rds_superuser_member
FROM pg_roles r
WHERE r.rolname NOT LIKE 'pg\_%'
  AND (r.rolbypassrls OR r.rolsuper)
ORDER BY r.rolcanlogin DESC, r.rolname;
