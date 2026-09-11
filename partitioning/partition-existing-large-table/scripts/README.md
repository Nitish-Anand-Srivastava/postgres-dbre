# Scripts: Partitioning an Existing Large Production Table

Execution order, safety classification, and expected runtime for every script
in `partitioning/partition-existing-large-table/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_partition_key_distribution.sql` | Analyzes the data distribution of the chosen candidate partition key to validate range/list boundary choices and detect skew. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_partition_sizing_estimate.sql` | Estimates resulting partition sizes given a proposed bucketing granularity, to avoid creating either too many tiny partitions or too few oversized ones. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_dependent_objects_inventory.sql` | Inventories every index, constraint, trigger, view, and foreign key touching the candidate table that must be recreated or adapted on the new partitioned structure. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_row_count_baseline.sql` | Captures the authoritative pre-migration row count and a lightweight checksum baseline for later validation. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_create_partitioned_replacement_table.md` | Creates the new partitioned replacement table structure (empty), matching the source table's columns and defaults. | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) | Variable -- depends on table size and chosen batch size; see runbook. |
| 06 | `06_create_partitions_and_indexes.md` | Creates the individual partitions and recreates indexes/constraints on the new partitioned table. | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) | Variable -- depends on table size and chosen batch size; see runbook. |
| 07 | `07_backfill_historical_data_batches.md` | Backfills historical data from the original table into the new partitioned table in small, committed batches. | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) | Variable -- depends on table size and chosen batch size; see runbook. |
| 08 | `08_dual_write_or_cdc_sync_delta.md` | Keeps the new partitioned table current with ongoing writes made to the original table while the batched backfill (script 07) is in progress. | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) | Variable -- depends on table size and chosen batch size; see runbook. |
| 09 | `09_validation_row_counts_checksums.sql` | Compares row counts and checksums between the original and new partitioned table before cutover. | READ ONLY | Low (sub-second to a few seconds) |
| 10 | `10_cutover_procedure.md` | Performs the brief, controlled cutover from the original table to the new partitioned table using an atomic rename swap. | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) | Variable -- depends on table size and chosen batch size; see runbook. |
| 11 | `11_rollback_plan.md` | Rollback procedure if validation fails post-cutover, or if the cutover itself must be aborted. | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) | Variable -- depends on table size and chosen batch size; see runbook. |

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

- The table has foreign keys referencing it from tables you do not control/cannot coordinate a migration with -- escalate to database engineering and the owning teams before proceeding; this is the most common source of partitioning migrations stalling mid-way.
- Any validation step (row count/checksum mismatch) fails -- halt the migration and escalate immediately; do not proceed to cutover with unvalidated data.

## Scripts That Should Not Be Run During Severe Incidents

- 05_create_partitioned_replacement_table.md -- Varies by step -- read each step's own warning before executing it.
- 06_create_partitions_and_indexes.md -- Varies by step -- read each step's own warning before executing it.
- 07_backfill_historical_data_batches.md -- Varies by step -- read each step's own warning before executing it.
- 08_dual_write_or_cdc_sync_delta.md -- Varies by step -- read each step's own warning before executing it.
- 10_cutover_procedure.md -- Varies by step -- read each step's own warning before executing it.
- 11_rollback_plan.md -- Varies by step -- read each step's own warning before executing it.
