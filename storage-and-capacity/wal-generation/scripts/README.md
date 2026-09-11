# Scripts: WAL Generation Investigation

Execution order, safety classification, and expected runtime for every script
in `storage-and-capacity/wal-generation/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_cluster_wal_activity.sql` | Cluster WAL counters (with Aurora availability detection). | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_checkpoint_activity.sql` | Checkpoint frequency and forced-checkpoint share. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_wal_settings_and_position.sql` | WAL configuration plus current WAL position. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_wal_heavy_statements.sql` | Top WAL-generating statements. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_write_volume_by_table.sql` | Per-table write volume and HOT update ratio. | READ ONLY | Low (sub-second to a few seconds) |
| 06 | `06_replication_slot_wal_retention.sql` | Replication slots retaining WAL. | READ ONLY | Low (sub-second to a few seconds) |

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

- Reader lag is high enough that reads are returning materially stale balances or order states to customers -- this is a customer-facing correctness issue and should be treated as an incident.
- A replication slot is retaining enough WAL to threaten cluster storage and the consumer cannot be contacted or recovered -- escalate for an authoritative decision to drop it.
- WAL generation has stepped up sharply with no deployment, no volume change, and no identifiable batch job -- investigate as unexpected-storage-growth and involve application engineering.
- CloudWatch shows write I/O rising while every in-database write counter is flat -- that discrepancy is not explainable from inside the database and needs an AWS support case.

## Scripts That Should Not Be Run During Severe Incidents

_All scripts in this workflow are lightweight, read-only, and safe to run even during a severe incident. Prefer the narrower/most targeted script first if the system is under extreme load._
