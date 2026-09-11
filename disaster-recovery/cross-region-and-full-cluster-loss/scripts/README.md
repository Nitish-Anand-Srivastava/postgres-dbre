# Scripts: Cross-Region Failover and Full Cluster Loss Recovery

Execution order, safety classification, and expected runtime for every script
in `disaster-recovery/cross-region-and-full-cluster-loss/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_pre_incident_baseline_reference.sql` | Captures a lightweight baseline (engine version, current database, and connection role) intended to be kept on file for comparison after a cross-region recovery, run periodically as part of standing DR preparedness rather than during the event itself. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_cross_region_and_full_loss_runbook.md` | Guarded runbook covering both recovery paths for a true regional-scale event: Aurora Global Database managed failover, and cross-region snapshot-copy restore when no Global Database is in place. | ELEVATED RISK (regional-scale recovery action -- either promotes a secondary region as the new production primary, or restores a new cluster from a potentially-hours-old cross-region snapshot copy) | Minutes for a Global Database failover; tens of minutes to hours for a cross-region snapshot restore plus instance provisioning, depending on data volume and cross-region transfer. |

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

- Any true regional-loss event triggers this workflow -- by definition, escalate to the highest level of incident command your organization has immediately; this is not a DBA-only response.

## Scripts That Should Not Be Run During Severe Incidents

- 02_cross_region_and_full_loss_runbook.md -- A managed Global Database failover accepts a small (sub-second to low-single-digit-second) data-loss window; a snapshot-copy restore accepts a data-loss window bounded by the copy schedule's frequency, typically much larger.
