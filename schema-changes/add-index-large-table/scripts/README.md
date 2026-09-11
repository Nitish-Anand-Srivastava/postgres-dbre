# Scripts: Adding an Index to a Large Table

Execution order, safety classification, and expected runtime for every script
in `schema-changes/add-index-large-table/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_sequential_scan_evidence.sql` | Tables suffering expensive sequential scans. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_existing_index_inventory.sql` | Existing indexes and constraints on the target table. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_write_volume_and_hot_ratio.sql` | Per-table write volume and HOT update ratio. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_target_table_size.sql` | Target table size and maintenance state. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_large_table_index_build_runbook.md` | Guarded DDL runbook: building an index on a very large table. | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) | Hours on a multi-hundred-gigabyte table; roughly 2-3x a plain build. |
| 06 | `06_build_progress_and_validity.sql` | Live build progress plus post-build validity check. | READ ONLY | Low (sub-second to a few seconds) |

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

- The build's estimated duration spans a market event or a scheduled deployment window.
- Reader lag during the build reaches a level that affects customer-facing reads -- treat as an incident and cancel.
- The table is large enough that the build cannot realistically complete in any acceptable window, which means the answer is partitioning rather than indexing.
- The proposed index would be the tenth or more on a table on the trading path -- that needs an index-set review, not another addition.

## Scripts That Should Not Be Run During Severe Incidents

- 05_large_table_index_build_runbook.md -- Varies by step -- read each step's own warning before executing it.
