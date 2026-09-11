# Scripts: Aurora Cluster Failover Drill

Execution order, safety classification, and expected runtime for every script
in `disaster-recovery/cluster-failover-drill/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_confirm_writer_reader_topology.sql` | Confirms current writer/reader role, run against each endpoint the application actually uses (cluster/writer endpoint and reader endpoint), as the pre-drill topology baseline. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_reader_health_and_lag_precheck.sql` | Confirms every reader's replication lag is low immediately before triggering the drill, so the drill measures the failover mechanism itself rather than a pre-existing lag problem. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_failover_drill_runbook.md` | Guarded runbook for triggering the actual Aurora failover via the AWS control plane and observing application-visible impact during the cutover. | ELEVATED RISK (deliberately disrupts every existing connection to the cluster for the duration of the cutover -- an AWS control-plane action, not a SQL statement) | Typically under a minute for the cutover itself; allow additional time afterward for full application-side recovery observation. |
| 04 | `04_post_failover_verification.sql` | Confirms the new writer's identity and how recently it started, run against the cluster/writer endpoint immediately after the drill to verify the promotion completed as expected. | READ ONLY | Low (sub-second to a few seconds) |

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

- The application does not recover within a reasonable window (several minutes) without manual intervention -- treat this as the drill's primary finding and open a tracking issue with the owning application team immediately, since the next failover may not be a scheduled drill.

## Scripts That Should Not Be Run During Severe Incidents

- 03_failover_drill_runbook.md -- A brief (typically tens of seconds) period where the cluster/reader endpoints are unavailable or reset for existing connections while the promoted reader becomes the new writer and DNS re-points.
