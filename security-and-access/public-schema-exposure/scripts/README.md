# Scripts: Public Schema and Default-Privilege Exposure

Execution order, safety classification, and expected runtime for every script
in `security-and-access/public-schema-exposure/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_public_schema_privilege_posture.sql` | Directly tests what the PUBLIC pseudo-role can do on the `public` schema, and lists any broadly-scoped ALTER DEFAULT PRIVILEGES entries. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_objects_granted_to_public.sql` | Lists individual tables/views/materialized views inside `public` that were explicitly granted directly to the PUBLIC pseudo-role, independent of the schema-level privileges checked in script 01. | READ ONLY | Low (sub-second to a few seconds) |

## Execution Order

Run scripts strictly in the numeric order shown above. Each script assumes the
operator has reviewed the output of the prior step. Do not skip ahead to a
remediation template (`.md` files, if present) without completing the
read-only investigation steps first.

## Required Permissions

Unless a script states otherwise in its `REQUIRED PRIVILEGES` header field, a
role with the built-in `pg_monitor` (or `pg_read_all_stats` /
`pg_read_all_settings`) attribute, `CONNECT` on the target database, and
`USAGE` on `public` is sufficient. Scripts that read `pg_stat_statements`
require that extension to be installed in the current database. Scripts that
touch DDL, `pg_terminate_backend()`, or write operations state elevated
requirements explicitly in their own header.

## Expected Output

Every script returns a result set intended to be read directly in `psql` (or
any SQL client). Columns are named for direct interpretation; each script's
header contains a `HOW TO INTERPRET RESULTS` section, and the parent
`README.md` section 8 ("Interpretation Guide") gives workflow-level guidance.

## When to Stop and Escalate

- public_role_can_create = true is found on a database holding customer or financial data with no documented justification -- escalate to the security team before the next scheduled deploy touches that schema.

## Scripts That Should Not Be Run During Severe Incidents

_All scripts in this workflow are lightweight, read-only, and safe to run even during a severe incident. Prefer the narrower/most targeted script first if the system is under extreme load._
