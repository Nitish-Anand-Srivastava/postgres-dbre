# Scripts: Backup and Restore Validation

Execution order, safety classification, and expected runtime for every script
in `disaster-recovery/backup-and-restore-validation/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_restore_point_reference_snapshot.sql` | Captures a SQL-side reference point (current WAL position and database-level statistics) immediately before a scheduled test-restore, for concrete before/after comparison. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_backup_and_restore_test_runbook.md` | Guarded runbook for confirming backup/snapshot configuration via the AWS control plane and performing a periodic test-restore into a scratch cluster. | LOW RISK WRITE (creates a new, separate scratch cluster; does not modify or risk the production cluster) | Minutes to describe configuration; tens of minutes for the restore and instance provisioning, depending on data volume. |

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

- A scheduled test-restore fails, or the restored data does not match the pre-restore reference snapshot -- escalate to AWS Support and to the platform/compliance team immediately, since this means the organization's actual recovery capability does not match its assumed one.

## Scripts That Should Not Be Run During Severe Incidents

- 02_backup_and_restore_test_runbook.md -- No impact to the production cluster; creates temporary AWS infrastructure cost for the scratch cluster until it is decommissioned.
