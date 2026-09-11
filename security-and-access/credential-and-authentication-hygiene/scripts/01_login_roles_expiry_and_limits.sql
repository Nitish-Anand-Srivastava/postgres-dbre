/*
===============================================================================
SCRIPT NAME:
01_login_roles_expiry_and_limits.sql

PURPOSE:
Inventories every login-capable role with its password expiry, connection limit, IAM-auth status, and elevated attributes, ordered so never-expiring password credentials surface first.

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
Step 01 of workflow 'security-and-access/credential-and-authentication-hygiene'

RELATED SCRIPTS:
02_authentication_settings_and_role_overrides.sql

HOW TO INTERPRET RESULTS:
The top of this result is the work queue: login roles whose password never expires, superuser-adjacent first. uses_iam_auth = true materially lowers the risk for that row (the credential is a short-lived token, not a stored secret), so treat an IAM-only role with an expired password as a good end state rather than a finding. connection_limit = -1 means unlimited -- acceptable for a human admin role, questionable for a service role that has a fixed pool size on the client side. rolcreaterole/rolreplication/rolbypassrls being true on a service account are each privilege-escalation paths worth a separate justification.
===============================================================================
*/

-- Credential policy for every login-capable role. This reads pg_roles only:
-- pg_authid (which holds the actual password verifiers) is deliberately not
-- touched, so no credential material is ever returned by this script.
--
-- rolvaliduntil is the only expiry mechanism PostgreSQL itself enforces for
-- password authentication; a NULL value means the password never expires.
SELECT
    r.rolname                                                    AS role_name,
    r.rolvaliduntil                                              AS password_valid_until,
    CASE
        WHEN r.rolvaliduntil IS NULL      THEN 'never expires'
        WHEN r.rolvaliduntil <= now()     THEN 'already expired'
        ELSE 'expires in ' || date_trunc('day', r.rolvaliduntil - now())::text
    END                                                          AS expiry_status,
    r.rolconnlimit                                               AS connection_limit,
    EXISTS (
        SELECT 1
        FROM pg_auth_members m
        JOIN pg_roles g ON g.oid = m.roleid
        WHERE m.member = r.oid
          AND g.rolname = 'rds_iam'
    )                                                            AS uses_iam_auth,
    EXISTS (
        SELECT 1
        FROM pg_auth_members m
        JOIN pg_roles g ON g.oid = m.roleid
        WHERE m.member = r.oid
          AND g.rolname = 'rds_superuser'
    )                                                            AS is_rds_superuser_member,
    r.rolcreaterole,
    r.rolreplication,
    r.rolbypassrls,
    (SELECT count(*) FROM pg_stat_activity a WHERE a.usename = r.rolname) AS current_connections
FROM pg_roles r
WHERE r.rolcanlogin
  AND r.rolname NOT LIKE 'pg\_%'
ORDER BY
    (r.rolvaliduntil IS NULL) DESC,
    is_rds_superuser_member DESC,
    r.rolvaliduntil,
    r.rolname;
