# Scripts: Point-in-Time Recovery (PITR) Drill

Execution order, safety classification, and expected runtime for every script
in `disaster-recovery/point-in-time-recovery-drill/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_target_restore_time_reference.sql` | Given an operator-supplied suspected incident-start timestamp, computes a suggested restore-to target slightly earlier, alongside the current server time and WAL position for reference. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_point_in_time_recovery_runbook.md` | Guarded runbook for restoring the cluster to a specific point in time into a new cluster, using the target time identified by script 01. | LOW RISK WRITE (creates a new, separate cluster; does not modify the existing cluster in place) | Tens of minutes for the restore and instance provisioning, depending on data volume; validation and correction time varies with incident scope. |

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

- The incident-start time cannot be identified with reasonable confidence from available logs/timestamps -- escalate to restore multiple candidate points in parallel (as separate scratch clusters) rather than guessing a single target time for a data-integrity-critical restore.

## Scripts That Should Not Be Run During Severe Incidents

- 02_point_in_time_recovery_runbook.md -- No impact to the existing production cluster; creates temporary AWS infrastructure cost for the recovery cluster until it is decommissioned.
