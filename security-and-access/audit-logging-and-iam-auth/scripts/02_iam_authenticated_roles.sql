/*
===============================================================================
SCRIPT NAME:
02_iam_authenticated_roles.sql

PURPOSE:
Lists every role currently granted IAM database authentication via membership in the built-in rds_iam role.

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
Step 02 of workflow 'security-and-access/audit-logging-and-iam-auth'

RELATED SCRIPTS:
03_installing_pgaudit_and_granting_iam_auth.md

HOW TO INTERPRET RESULTS:
Every role listed here can authenticate using a short-lived IAM auth token rather than a static password. Any login-capable role you would expect to see here but do not is still relying on password authentication -- see the runbook for how to add it.
===============================================================================
*/

-- rds_iam membership is how IAM database authentication is granted per role
-- on Aurora/RDS PostgreSQL. A role NOT in this list authenticates using a
-- traditional password (or another configured method) instead.
SELECT
    r.rolname                                                   AS role_name,
    r.rolcanlogin
FROM pg_auth_members m
JOIN pg_roles g ON g.oid = m.roleid
JOIN pg_roles r ON r.oid = m.member
WHERE g.rolname = 'rds_iam'
ORDER BY r.rolname;
