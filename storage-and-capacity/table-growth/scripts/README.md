# Scripts: Table Growth Investigation

Execution order, safety classification, and expected runtime for every script
in `storage-and-capacity/table-growth/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_largest_tables.sql` | Top relations by total size. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_table_size_components.sql` | Heap / TOAST / index split per relation. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_write_volume_by_table.sql` | Per-table write volume and HOT update ratio. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_dead_tuples_ranked.sql` | Dead tuple accumulation per table. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_measured_growth_from_history.sql` | Measured per-table growth over the history window. | READ ONLY | Low (sub-second to a few seconds) |
| 06 | `06_single_table_deep_dive.sql` | Single-table size, row estimates, and maintenance recency. | READ ONLY | Low (sub-second to a few seconds) |

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

- The fastest-growing table is the financial ledger or another relation under a regulatory retention mandate -- archival design needs compliance sign-off before any DBA action.
- Growth rate has more than doubled with no corresponding change in trading volume or deployment -- treat it as unexpected-storage-growth rather than normal capacity planning.
- Remediation requires partitioning a table that is on the live order-placement path -- that migration needs database engineering leadership and a formal change window.
- Dead tuples remain high across multiple autovacuum cycles despite no long-running transactions and no lagging replication slots -- escalate to the vacuum category and, if unexplained, to AWS support.

## Scripts That Should Not Be Run During Severe Incidents

_All scripts in this workflow are lightweight, read-only, and safe to run even during a severe incident. Prefer the narrower/most targeted script first if the system is under extreme load._
