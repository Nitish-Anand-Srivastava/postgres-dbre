/*
===============================================================================
SCRIPT NAME:
01_public_schema_privilege_posture.sql

PURPOSE:
Directly tests what the PUBLIC pseudo-role can do on the `public` schema, and lists any broadly-scoped ALTER DEFAULT PRIVILEGES entries.

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
Step 01 of workflow 'security-and-access/public-schema-exposure'

RELATED SCRIPTS:
02_objects_granted_to_public.sql

HOW TO INTERPRET RESULTS:
public_role_can_create = true means any login-capable role can create objects in `public` -- confirm this is deliberate. Any default-privilege row with grantee = 'public' silently grants every future object of that type, in that scope, to every role in the cluster -- treat this as high priority regardless of how narrow the object_type looks.
===============================================================================
*/

-- has_schema_privilege() answers "can PUBLIC do X on schema public" directly,
-- which is more reliable than reading pg_namespace.nspacl by hand: a NULL
-- nspacl means "the compiled-in default for this object type", and that
-- default itself differs depending on whether this database was created
-- before or after the PostgreSQL 15 public-schema default change -- letting
-- the privilege functions resolve that ambiguity avoids getting it wrong.
SELECT
    'public'                                                     AS schema_name,
    has_schema_privilege('public', 'public', 'CREATE')            AS public_role_can_create,
    has_schema_privilege('public', 'public', 'USAGE')             AS public_role_can_use;

-- Any ALTER DEFAULT PRIVILEGES entries currently in effect, and exactly
-- which grantee/object-type/schema combination they apply to. A row with a
-- NULL applies_to_schema applies cluster-wide across every schema owned by
-- defaclrole -- the broadest, and therefore highest-review-priority, kind
-- of default-privilege entry.
SELECT
    n.nspname                                                    AS applies_to_schema,
    d.defaclrole::regrole::text                                  AS owning_role,
    d.defaclobjtype                                               AS object_type,
    a.grantee::regrole::text                                     AS grantee,
    a.privilege_type
FROM pg_default_acl d
LEFT JOIN pg_namespace n ON n.oid = d.defaclnamespace
CROSS JOIN LATERAL aclexplode(d.defaclacl) AS a
ORDER BY applies_to_schema NULLS FIRST, owning_role, object_type, grantee;
