# Scripts: Database Growth Investigation

Execution order, safety classification, and expected runtime for every script
in `storage-and-capacity/database-growth/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_database_sizes.sql` | Per-database logical size ranking. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_schema_size_breakdown.sql` | Per-schema size and share of user data. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_largest_tables.sql` | Top relations by total size. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_table_size_components.sql` | Heap / TOAST / index split for the largest relations. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_largest_indexes.sql` | Top indexes by size. | READ ONLY | Low (sub-second to a few seconds) |
| 06 | `06_object_counts_and_growth_history.sql` | Object counts per schema plus measured growth from size history. | READ ONLY | Low to moderate (a few seconds; longer on a database with tens of thousands of partitions). |

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

- Cluster volume growth is on a trajectory to reach the Aurora 128 TiB volume limit within the forecast horizon -- involve AWS support and database engineering leadership immediately.
- The largest and fastest-growing relation is the financial ledger, where no data may be deleted for regulatory reasons -- this needs a compliance-approved archival design, not a DBA-level fix.
- PostgreSQL-reported logical size is flat or falling while CloudWatch `VolumeBytesUsed` keeps climbing -- that pattern is not explainable from inside the database and needs an AWS support case.
- Growth rate has changed abruptly (a step change rather than a trend) with no corresponding deployment or volume event -- treat it as unexpected-storage-growth and investigate as a possible defect or runaway process.

## Scripts That Should Not Be Run During Severe Incidents

_All scripts in this workflow are lightweight, read-only, and safe to run even during a severe incident. Prefer the narrower/most targeted script first if the system is under extreme load._
