# Public Schema and Default-Privilege Exposure

**Category:** Security and Access | **Workflow:** `security-and-access/public-schema-exposure`

## 1. Problem Description

Reviews exactly what the `public` schema and its objects actually grant to the PUBLIC pseudo-role on this specific database, since PostgreSQL 15 changed the shipped defaults and it is unsafe to assume either the old or the new behavior without verifying.

## 2. Typical Symptoms

- A security review asks 'can any authenticated role create objects in public, or read tables that were only intended for a specific application role'.
- A newly created role can unexpectedly SELECT from a table nobody explicitly granted it access to.

## 3. Business Impact

- Because PostgreSQL 15 changed the built-in default (CREATE on `public` is no longer granted to PUBLIC on databases created under PG15+), a cluster upgraded across that boundary, or one with mixed database-creation history, can have inconsistent exposure per database -- assuming a uniform posture across an Aurora PostgreSQL 17 cluster without checking is itself the risk.

## 4. Possible Root Causes

- A database created before the PG15 default change (or restored/migrated from one) still carries the older, more permissive public-schema ACL, since the change only affects newly initialized databases, not existing ones carried forward through an upgrade.
- An explicit `GRANT ... TO PUBLIC` was added at some point (on the schema or on individual objects) for a legitimate but now-forgotten reason.
- `ALTER DEFAULT PRIVILEGES` was set broadly (for all roles, all schemas) rather than scoped to a specific role/schema, silently applying to every future object.

## 5. Investigation Strategy

1. Directly test what the PUBLIC pseudo-role can actually do on the `public` schema using has_schema_privilege(), rather than trying to infer it from a potentially-NULL ACL column.
2. Check for any ALTER DEFAULT PRIVILEGES entries that apply broadly.
3. Check for individual objects inside `public` that were explicitly granted to PUBLIC directly (not just via the schema's own privileges).

## 6. Prerequisites

- Read access to pg_namespace/pg_default_acl/pg_class (standard for any authenticated role).

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_public_schema_privilege_posture.sql`](scripts/01_public_schema_privilege_posture.sql) -- Directly tests what the PUBLIC pseudo-role can do on the `public` schema, and lists any broadly-scoped ALTER DEFAULT PRIVILEGES entries.
2. [`scripts/02_objects_granted_to_public.sql`](scripts/02_objects_granted_to_public.sql) -- Lists individual tables/views/materialized views inside `public` that were explicitly granted directly to the PUBLIC pseudo-role, independent of the schema-level privileges checked in script 01.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- PostgreSQL 15 changed the default so that newly created databases no longer grant CREATE on the `public` schema to PUBLIC (USAGE is still granted) -- Aurora PostgreSQL 17 inherits this upstream default for databases created directly on 17, but a database carried forward from an earlier engine version via in-place major-version upgrade retains whatever ACL it already had. Always verify with has_schema_privilege() rather than assuming either default.

## 8. Interpretation Guide

- public_role_can_create = true means any login-capable role in the cluster can create objects inside the `public` schema -- on Aurora PostgreSQL 17 databases created fresh this is normally false (the PG15+ default); true on such a database is worth understanding, not assuming is fine because 'it has always been that way'.
- public_role_can_use = true (USAGE on the schema) is the PG15+ default and, by itself, is not a finding -- USAGE only allows referencing objects in the schema, not creating or reading them; CREATE and per-object SELECT/INSERT/etc are the privileges that actually matter.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- None -- this is a review workflow, not an active-incident one, unless a specific unauthorized-access finding from role-and-privilege-audit points here.

**Short-term remediation** (hours to days):

- If public_role_can_create = true and is not a deliberate, documented choice, run `REVOKE CREATE ON SCHEMA public FROM PUBLIC;` (a guarded DDL step, change-managed) to bring the database in line with the current PostgreSQL default.
- Remove any individual object grants to PUBLIC found in script 02 that are not deliberately intended to be readable/writable by every role in the cluster.

**Long-term engineering fix** (days to weeks):

- Scope every ALTER DEFAULT PRIVILEGES statement to a specific role and schema going forward, never a blanket grant, and document each one alongside the schema/role design.

## 10. Production Safety

- All scripts in this workflow are read-only; the REVOKE mentioned in remediation is a DDL change and must go through the same change-management process as any other privilege change, not be run ad hoc from this investigation.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- public_role_can_create = true is found on a database holding customer or financial data with no documented justification -- escalate to the security team before the next scheduled deploy touches that schema.

## 12. Related Issues

- [role-and-privilege-audit](../role-and-privilege-audit/README.md)
- [audit-logging-and-iam-auth](../audit-logging-and-iam-auth/README.md)
