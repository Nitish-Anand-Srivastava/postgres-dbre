# Scripts: Unused and Orphaned Roles

Execution order, safety classification, and expected runtime for every script
in `security-and-access/unused-and-orphaned-roles/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_candidate_roles_by_activity_and_ownership.sql` | Ranks every non-system role by current connection count, objects owned, and group-membership purpose, surfacing the roles with the least evidence of ongoing legitimate use first. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_role_cleanup_runbook.md` | Guarded, manual runbook for reassigning ownership away from and then dropping a role confirmed abandoned by script 01 and by cross-referencing your service/employee inventory. | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) | Variable -- depends on table size and chosen batch size; see runbook. |

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

- A candidate role turns out to still be referenced by application connection-string configuration or infrastructure-as-code even though it shows zero current connections -- treat this as a near-miss and escalate to the owning team before it is actually dropped.

## Scripts That Should Not Be Run During Severe Incidents

- 02_role_cleanup_runbook.md -- Varies by step -- read each step's own warning before executing it.
