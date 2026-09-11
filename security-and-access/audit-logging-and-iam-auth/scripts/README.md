# Scripts: Audit Logging (pgaudit) and IAM Database Authentication

Execution order, safety classification, and expected runtime for every script
in `security-and-access/audit-logging-and-iam-auth/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_pgaudit_installation_and_scope.sql` | Checks whether the pgaudit extension is installed and, if so, reports its current logging-scope configuration. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_iam_authenticated_roles.sql` | Lists every role currently granted IAM database authentication via membership in the built-in rds_iam role. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_installing_pgaudit_and_granting_iam_auth.md` | Guarded runbook for installing pgaudit (change-managed, reboot-driving) and for granting IAM database authentication to a role. | LOW RISK WRITE (shared_preload_libraries parameter-group change requires a reboot; CREATE EXTENSION and GRANT are schema/role changes -- see runbook for sequencing) | Minutes for the GRANT; a full maintenance-window reboot cycle for the shared_preload_libraries change to take effect. |

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

- A compliance deadline requires object-level audit evidence and pgaudit is confirmed not installed -- escalate to the platform/compliance team immediately, since installing it requires a reboot-driven maintenance window that needs lead time to schedule.

## Scripts That Should Not Be Run During Severe Incidents

- 03_installing_pgaudit_and_granting_iam_auth.md -- pgaudit adds per-statement logging overhead proportional to its configured scope once installed and enabled; granting rds_iam has no impact until the client is updated to use an IAM token.
