# Partitioning an Existing Large Production Table

**Category:** Partitioning | **Workflow:** `partitioning/partition-existing-large-table`

## 1. Problem Description

A comprehensive, realistic Staff DBA runbook for migrating an existing, already-large, in-production table to a native PostgreSQL declarative-partitioned structure with minimal downtime and controlled risk. This is deliberately NOT a single `ALTER TABLE ... PARTITION BY` -- PostgreSQL does not support converting an existing table in place; a new partitioned table must be built alongside it, backfilled, kept in sync, validated, and cut over.

## 2. Typical Symptoms

- The table has been confirmed a strong partitioning candidate (see investigate-partitioning-candidate) and a migration has been approved.

## 3. Business Impact

- A well-executed partitioned migration materially improves vacuum efficiency, query pruning, and archive/retention operations for a large, continuously growing table -- but a poorly executed one risks extended downtime, data loss, or referential-integrity breaks on a business-critical table.

## 4. Possible Root Causes

- N/A -- this is a planned migration runbook.

## 5. Investigation Strategy

1. Confirm partition key selection and strategy (range/list/hash) against the query-pattern review from investigate-partitioning-candidate.
2. Inventory every constraint, index, and foreign key relationship that must be recreated on the new structure.
3. Estimate partition count/sizing.
4. Build the new partitioned table and its partitions/indexes alongside the existing table.
5. Backfill historical data in controlled batches.
6. Establish a delta-sync mechanism (trigger-based dual-write or logical replication) to keep the new table current with ongoing writes during backfill.
7. Validate row counts and checksums between old and new tables.
8. Perform a brief, controlled cutover (rename swap) inside a short transaction.
9. Validate the application against the new structure post-cutover.
10. Retain the old table (renamed, not dropped) for a rollback window before final cleanup.

## 6. Prerequisites

- A confirmed partition key and strategy from investigate-partitioning-candidate.
- A maintenance window or low-traffic period for the final cutover step specifically (the backfill/sync steps themselves are designed to run online).
- Table-owner/DDL privileges and explicit change-management approval given the business criticality implied by 'large production table'.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_partition_key_distribution.sql`](scripts/01_partition_key_distribution.sql) -- Analyzes the data distribution of the chosen candidate partition key to validate range/list boundary choices and detect skew.
2. [`scripts/02_partition_sizing_estimate.sql`](scripts/02_partition_sizing_estimate.sql) -- Estimates resulting partition sizes given a proposed bucketing granularity, to avoid creating either too many tiny partitions or too few oversized ones.
3. [`scripts/03_dependent_objects_inventory.sql`](scripts/03_dependent_objects_inventory.sql) -- Inventories every index, constraint, trigger, view, and foreign key touching the candidate table that must be recreated or adapted on the new partitioned structure.
4. [`scripts/04_row_count_baseline.sql`](scripts/04_row_count_baseline.sql) -- Captures the authoritative pre-migration row count and a lightweight checksum baseline for later validation.
5. [`scripts/05_create_partitioned_replacement_table.md`](scripts/05_create_partitioned_replacement_table.md) -- Creates the new partitioned replacement table structure (empty), matching the source table's columns and defaults.
6. [`scripts/06_create_partitions_and_indexes.md`](scripts/06_create_partitions_and_indexes.md) -- Creates the individual partitions and recreates indexes/constraints on the new partitioned table.
7. [`scripts/07_backfill_historical_data_batches.md`](scripts/07_backfill_historical_data_batches.md) -- Backfills historical data from the original table into the new partitioned table in small, committed batches.
8. [`scripts/08_dual_write_or_cdc_sync_delta.md`](scripts/08_dual_write_or_cdc_sync_delta.md) -- Keeps the new partitioned table current with ongoing writes made to the original table while the batched backfill (script 07) is in progress.
9. [`scripts/09_validation_row_counts_checksums.sql`](scripts/09_validation_row_counts_checksums.sql) -- Compares row counts and checksums between the original and new partitioned table before cutover.
10. [`scripts/10_cutover_procedure.md`](scripts/10_cutover_procedure.md) -- Performs the brief, controlled cutover from the original table to the new partitioned table using an atomic rename swap.
11. [`scripts/11_rollback_plan.md`](scripts/11_rollback_plan.md) -- Rollback procedure if validation fails post-cutover, or if the cutover itself must be aborted.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Aurora PostgreSQL supports the pg_partman extension for ongoing partition maintenance (creating future partitions, dropping/archiving old ones automatically) -- consider adopting it (see partition-maintenance) once the initial migration in this runbook is complete, rather than only for the migration itself.

## 8. Interpretation Guide

- The backfill and delta-sync phases can run for hours/days on a very large table without any application downtime -- only the final cutover step needs a brief exclusive lock (typically milliseconds to low seconds using an atomic rename swap), which is why this runbook separates 'safe to run online, take your time' steps from the single 'brief locking window' step.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- N/A -- see the rollback runbook (script 11) if a specific step must be aborted mid-migration.

**Short-term remediation** (hours to days):

- N/A.

**Long-term engineering fix** (days to weeks):

- After a successful cutover and a confirmed rollback-safe period, drop the old (renamed) table and any now-redundant dual-write triggers.

## 10. Production Safety

- Every DDL/DML step in this workflow is provided as a guarded `.md` runbook template, not a ready-to-run `.sql` script, and requires the operator to substitute real schema/table/column names and review locking behavior before execution.
- The backfill step must run in small, committed batches -- never as one large transaction -- to avoid long-held locks, excessive WAL generation, and replica lag.
- The cutover step is the only step that takes a brief strong lock; every other step is designed to be safely run against a live, fully-online production table.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- The table has foreign keys referencing it from tables you do not control/cannot coordinate a migration with -- escalate to database engineering and the owning teams before proceeding; this is the most common source of partitioning migrations stalling mid-way.
- Any validation step (row count/checksum mismatch) fails -- halt the migration and escalate immediately; do not proceed to cutover with unvalidated data.

## 12. Related Issues

- [investigate-partitioning-candidate](../investigate-partitioning-candidate/README.md)
- [partition-maintenance](../partition-maintenance/README.md)
- [large-table-ddl](../../schema-changes/large-table-ddl/README.md)
