# Scripts: Role and Privilege Audit

Execution order, safety classification, and expected runtime for every script
in `security-and-access/role-and-privilege-audit/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_current_role_capabilities.sql` | Confirms what the currently connected auditing role itself can do -- its super/create/replication attributes and its own group memberships -- as context for interpreting the rest of the audit. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_all_roles_and_memberships.sql` | Enumerates every non-system role in the cluster along with its login/create/replication attributes and its full group-membership list. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_object_level_grants_by_schema.sql` | Enumerates explicit, individually-granted table/view/materialized-view privileges across all non-system schemas, the grants that bypass group-role membership entirely. | READ ONLY | Low (sub-second to a few seconds) |

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

- Any role with rolsuper = true, or an unexplained rolbypassrls = true, is found -- escalate to the security team immediately regardless of audit cadence.
- A role is found with object-level access it has no documented business justification for -- escalate to the role's owning team before revoking, in case the access is load-bearing for an undocumented integration.

## Scripts That Should Not Be Run During Severe Incidents

_All scripts in this workflow are lightweight, read-only, and safe to run even during a severe incident. Prefer the narrower/most targeted script first if the system is under extreme load._
