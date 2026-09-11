# Scripts: Unexpected Storage Growth

Execution order, safety classification, and expected runtime for every script
in `storage-and-capacity/unexpected-storage-growth/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_database_size_snapshot.sql` | Per-database size snapshot for baseline comparison. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_largest_tables_snapshot.sql` | Relation size snapshot for baseline comparison. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_dead_tuple_accumulation.sql` | Dead tuple accumulation per table. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_xmin_horizon_holders.sql` | Transactions and prepared transactions pinning the xmin horizon. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_replication_slot_retention.sql` | Replication slots retaining WAL and pinning xmin. | READ ONLY | Low (sub-second to a few seconds) |
| 06 | `06_temp_file_and_local_storage.sql` | Temp file usage per database. | READ ONLY | Low (sub-second to a few seconds) |
| 07 | `07_index_builds_and_invalid_indexes.sql` | Running index builds plus INVALID index leftovers. | READ ONLY | Low (sub-second to a few seconds) |

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

- The Aurora volume is growing while every in-database metric is flat and no slot, build, or temp file activity explains it -- open an AWS support case with the CloudWatch timeline attached.
- The same root cause holding back the xmin horizon is also driving transaction age upward -- this is a wraparound risk and takes priority over the storage symptom entirely.
- An abandoned replication slot is retaining enough WAL to threaten cluster storage and its owner cannot be identified or contacted -- escalate for an authoritative decision to drop it.
- Growth is traced to an application defect actively writing unbounded data -- escalate to application engineering as a production incident, since every minute of delay is permanent Aurora storage.
- Remediation would require terminating sessions on the trading path, or dropping a relation whose ownership is unclear -- both need explicit authorization above the on-call DBA.

## Scripts That Should Not Be Run During Severe Incidents

_All scripts in this workflow are lightweight, read-only, and safe to run even during a severe incident. Prefer the narrower/most targeted script first if the system is under extreme load._
