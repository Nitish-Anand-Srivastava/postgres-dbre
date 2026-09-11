# Scripts: Aurora Parameter Group Change Management

Execution order, safety classification, and expected runtime for every script
in `maintenance/parameter-group-change-management/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_key_settings_and_scope.sql` | Snapshots the settings most commonly changed operationally, including each one's context, which indicates whether it can be changed dynamically, via SIGHUP, or only at instance start. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_pending_restart_settings.sql` | Lists every setting currently flagged as changed-in-the-parameter-group-but-not-yet-applied, the direct signal that a reboot (or failover) is needed to finish a previously started change. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_parameter_group_change_runbook.md` | Guarded runbook for making an Aurora parameter-group change safely: validating on non-prod first, understanding ApplyType, and scheduling any required reboot. | LOW RISK WRITE (Aurora DB cluster/instance parameter group change; static parameters require a per-instance reboot to take effect -- see runbook) | Minutes to apply the parameter-group change itself; a full maintenance-window reboot cycle for any static parameter to take effect. |

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

- A parameter-group change is found in a pending-reboot state for longer than a routine maintenance window would explain -- escalate to confirm whether it was intentionally deferred or simply forgotten.

## Scripts That Should Not Be Run During Severe Incidents

- 03_parameter_group_change_runbook.md -- None until applied; a static parameter's eventual reboot causes a brief per-instance availability interruption, worse on the writer than on a reader.
