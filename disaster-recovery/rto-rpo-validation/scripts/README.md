# Scripts: RTO and RPO Validation

Execution order, safety classification, and expected runtime for every script
in `disaster-recovery/rto-rpo-validation/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_observable_recovery_point_signals.sql` | Captures every recovery-point signal the database itself can report: instance role, Aurora reader lag, and replication slot lag with retained WAL. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_recovery_reference_point.sql` | Records a durable, engine-safe reference point (server time and commit counters, plus LSN only where supported) for comparing against a restored cluster after a drill. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_rto_rpo_measurement_runbook.md` | AWS-side guidance for the recovery-window figures the database cannot report, and the procedure for measuring real RTO during the drills in this category. | INFORMATIONAL -- NO SQL EXECUTED, AWS CONSOLE/API GUIDANCE ONLY | Minutes for the describe calls; the measurement procedure runs for the duration of whichever drill it is attached to. |
| 04 | `04_recovery_objectives_register.md` | The standing register: how to record each drill's measured results against the documented business targets so gaps stay visible between drills. | DOCUMENTATION -- no SQL executed by this file itself | Minutes per drill to record results. |

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

- A measured recovery time or recovery point misses the documented business target by a material margin -- escalate to the platform and compliance owners, since the organization is operating against a DR policy it cannot currently meet.
- The cross-region recovery point (Global Database lag or cross-region snapshot copy age) is materially worse than the policy assumes and no Global Database is configured -- escalate as an architectural gap rather than an operational one.

## Scripts That Should Not Be Run During Severe Incidents

- 03_rto_rpo_measurement_runbook.md -- None. Every command shown is a read-only AWS describe call; no recovery action is triggered by this file.
- 04_recovery_objectives_register.md -- None from this file directly; the drills it records results from carry their own impact, documented in their own workflows.
