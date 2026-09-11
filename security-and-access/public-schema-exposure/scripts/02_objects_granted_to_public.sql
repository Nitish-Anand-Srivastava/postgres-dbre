/*
===============================================================================
SCRIPT NAME:
02_objects_granted_to_public.sql

PURPOSE:
Lists individual tables/views/materialized views inside `public` that were explicitly granted directly to the PUBLIC pseudo-role, independent of the schema-level privileges checked in script 01.

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
Step 02 of workflow 'security-and-access/public-schema-exposure'

RELATED SCRIPTS:
../role-and-privilege-audit/scripts/03_object_level_grants_by_schema.sql

HOW TO INTERPRET RESULTS:
Every row here is an object readable/writable (per privilege_type) by any authenticated role in the cluster, regardless of that role's own grants -- for a table holding customer or financial data, a SELECT-to-PUBLIC row here is almost always a finding worth revoking, not an intentional design choice.
===============================================================================
*/

-- Individual objects in the `public` schema with an explicit grant to the
-- PUBLIC pseudo-role (aclexplode grantee = 0 represents PUBLIC). This is
-- distinct from schema-level USAGE/CREATE: an object can be explicitly
-- opened to PUBLIC even when the schema-level defaults are otherwise tight.
SELECT
    c.relname                                                    AS relation_name,
    CASE c.relkind
        WHEN 'r' THEN 'table' WHEN 'p' THEN 'partitioned table'
        WHEN 'v' THEN 'view' WHEN 'm' THEN 'materialized view'
        ELSE c.relkind::text
    END                                                           AS relation_type,
    a.privilege_type,
    a.is_grantable
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
CROSS JOIN LATERAL aclexplode(c.relacl) AS a
WHERE n.nspname = 'public'
  AND c.relacl IS NOT NULL
  AND a.grantee = 0
ORDER BY relation_name, privilege_type;
