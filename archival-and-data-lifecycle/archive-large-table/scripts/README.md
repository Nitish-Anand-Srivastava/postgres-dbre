# Scripts: Archiving a Large Production Table

Execution order, safety classification, and expected runtime for every script
in `archival-and-data-lifecycle/archive-large-table/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_confirm_archive_boundary.sql` | Confirms the exact row count and boundary that will be affected by the approved retention cutoff, before any data movement begins. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_export_to_cold_storage.md` | Exports the to-be-archived rows to durable cold storage before any deletion, using batched, checkpointed exports. | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) | Variable -- depends on table size and chosen batch size; see runbook. |
| 03 | `03_validate_export_row_counts.sql` | Compares the exported row count against the confirmed source scope from script 01. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_spot_check_data_integrity.sql` | Spot-checks a sample of archived rows for full column-level integrity against the source, beyond just a row count match. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_batched_deletion.md` | Deletes the validated, archived rows from the source table in small, monitored batches -- the highest-risk step in this workflow. | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) | Variable -- depends on table size and chosen batch size; see runbook. |
| 06 | `06_post_archive_vacuum.sql` | Checks dead tuple accumulation after the batched deletion and confirms whether a manual VACUUM is warranted to reclaim space. | READ ONLY | Low (sub-second to a few seconds) |

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

- Any validation step fails (exported row count does not match source) -- halt immediately and do not proceed to deletion; escalate to database engineering.
- The retention boundary is later found to conflict with an active legal hold or audit -- escalate to legal/compliance immediately and pause the archive process.

## Scripts That Should Not Be Run During Severe Incidents

- 02_export_to_cold_storage.md -- Varies by step -- read each step's own warning before executing it.
- 05_batched_deletion.md -- Varies by step -- read each step's own warning before executing it.
