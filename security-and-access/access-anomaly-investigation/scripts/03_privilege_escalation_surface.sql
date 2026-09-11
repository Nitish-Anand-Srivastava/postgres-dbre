/*
===============================================================================
SCRIPT NAME:
03_privilege_escalation_surface.sql

PURPOSE:
Enumerates the standing escalation surface -- elevated role attributes, re-grantable privileges, and objects reachable by every role via PUBLIC -- to answer what an implicated identity could have reached.

AURORA POSTGRESQL VERSION:
Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise)

EXECUTION LOCATION:
Any instance (writer or reader)

SAFETY:
READ ONLY

EXPECTED IMPACT:
Minimal -- reads system catalogs/statistics views only, no table locks beyond a brief catalog lookup.

REQUIRED PRIVILEGES:
Role membership in `pg_monitor` (or `pg_read_all_stats`) is sufficient. No superuser required. Full visibility of role attributes and object ACLs may additionally require ownership of the objects concerned; a restricted role sees fewer rows rather than an error, so run this as the audit role used elsewhere in this category.

PREREQUISITES:
None beyond CONNECT on the target database.

EXECUTION ORDER:
Step 03 of workflow 'security-and-access/access-anomaly-investigation'

RELATED SCRIPTS:
04_access_anomaly_containment_runbook.md

HOW TO INTERPRET RESULTS:
Every row in the first result set is a standing escalation path; cross-check each against the identity implicated by scripts 01-02, and treat rolcreaterole on a service account as a finding in its own right regardless of this incident's outcome. In the second result set, 'PUBLIC (every role)' rows sort first and mean the implicated identity already had that access without any grant specific to it -- if a wallet, ledger, or order table appears there, the blast radius of the incident is every role in the cluster, not just the one you found. is_grantable = true rows explain how access can spread onward from a single compromised role.
===============================================================================
*/

-- Role attributes that constitute an escalation path in their own right.
-- rolcreaterole is the important one after superuser membership: a role that
-- can create roles can create one with privileges and then grant them to
-- itself, which is how a privilege "nobody granted" appears.
SELECT
    r.rolname                                                    AS role_name,
    r.rolcanlogin,
    r.rolcreaterole,
    r.rolcreatedb,
    r.rolreplication,
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
  AND (r.rolcreaterole OR r.rolcreatedb OR r.rolreplication OR r.rolbypassrls OR r.rolsuper)
ORDER BY r.rolsuper DESC, r.rolcreaterole DESC, r.rolname;

-- Object privileges that can be re-granted onward (WITH GRANT OPTION), plus
-- every privilege held by the PUBLIC pseudo-role. Both are ways an identity
-- reaches data without ever appearing in that object's expected grantee
-- list: a grantable privilege lets its holder extend access to others, and
-- a PUBLIC grant means every role in the cluster already has it.
SELECT
    n.nspname                                                    AS schema_name,
    c.relname                                                    AS relation_name,
    CASE
        WHEN a.grantee = 0 THEN 'PUBLIC (every role)'
        ELSE a.grantee::regrole::text
    END                                                          AS grantee,
    a.privilege_type,
    a.is_grantable,
    pg_get_userbyid(c.relowner)                                  AS object_owner
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
CROSS JOIN LATERAL aclexplode(c.relacl) AS a
WHERE c.relkind IN ('r', 'p', 'v', 'm')
  AND c.relacl IS NOT NULL
  AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
  AND (a.is_grantable OR a.grantee = 0)
ORDER BY (a.grantee = 0) DESC, schema_name, relation_name, grantee, a.privilege_type;
