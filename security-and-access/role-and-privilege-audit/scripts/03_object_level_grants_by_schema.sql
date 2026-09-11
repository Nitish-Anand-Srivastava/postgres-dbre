/*
===============================================================================
SCRIPT NAME:
03_object_level_grants_by_schema.sql

PURPOSE:
Enumerates explicit, individually-granted table/view/materialized-view privileges across all non-system schemas, the grants that bypass group-role membership entirely.

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
Step 03 of workflow 'security-and-access/role-and-privilege-audit'

RELATED SCRIPTS:
../public-schema-exposure/scripts/02_objects_granted_to_public.sql

HOW TO INTERPRET RESULTS:
A grantee of 'public' here means every role in the cluster (including future ones) has that privilege on that specific object -- treat any such row on a table containing customer/financial data as a high-priority finding, not a routine entry; see public-schema-exposure for the schema-level counterpart of this check.
===============================================================================
*/

-- Explicit object-level ACL entries on tables/views/materialized views in
-- every non-system schema. A row only appears here when a grant was made
-- directly against the object (GRANT ... ON object TO role) -- access
-- granted purely through role membership (e.g. the role's group has SELECT
-- on the schema via a default privilege) does not show up as a relacl
-- entry on the object itself, so treat this as a complement to, not a
-- replacement for, 02_all_roles_and_memberships.sql.
SELECT
    n.nspname                                                   AS schema_name,
    c.relname                                                   AS relation_name,
    CASE c.relkind
        WHEN 'r' THEN 'table' WHEN 'p' THEN 'partitioned table'
        WHEN 'v' THEN 'view' WHEN 'm' THEN 'materialized view'
        ELSE c.relkind::text
    END                                                          AS relation_type,
    a.grantee::regrole::text                                    AS grantee,
    a.privilege_type,
    a.is_grantable
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
CROSS JOIN LATERAL aclexplode(c.relacl) AS a
WHERE c.relkind IN ('r', 'p', 'v', 'm')
  AND c.relacl IS NOT NULL
  AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
ORDER BY schema_name, relation_name, grantee;
