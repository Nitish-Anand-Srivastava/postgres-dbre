# Archiving a Large Production Table

**Category:** Archiving and Data Lifecycle | **Workflow:** `archival-and-data-lifecycle/archive-large-table`

## 1. Problem Description

A comprehensive Staff DBA runbook for safely archiving historical data out of a very large, high-throughput production table -- covering boundary selection, batch export/migration, batch deletion without long locks or WAL spikes, partition-based detach/drop shortcuts where applicable, and validation before any destructive step.

## 2. Typical Symptoms

- The table has been confirmed an archiving candidate with an approved retention boundary (see investigate-archiving-candidate).

## 3. Business Impact

- Successful archiving reduces storage cost and improves vacuum/backup/query performance; a poorly executed archive risks data loss of records that may still be required for compliance/audit purposes.

## 4. Possible Root Causes

- N/A -- planned data-lifecycle operation.

## 5. Investigation Strategy

1. Confirm the exact retention boundary and compliance sign-off.
2. Export/copy the to-be-archived rows to durable, queryable cold storage before any deletion.
3. Validate the exported data completely and independently before deleting anything from the source table.
4. Delete the archived rows from the source table in small batches, monitoring WAL generation and replica lag throughout.
5. If the table is already partitioned by the archival boundary (e.g. by month), prefer DETACH PARTITION + separate archival of the detached partition over row-by-row DELETE.
6. Run a targeted VACUUM on the source table after large-scale deletion to reclaim space for reuse.

## 6. Prerequisites

- Compliance-approved retention boundary from investigate-archiving-candidate.
- A durable archive destination (e.g. an S3-backed cold-storage export via `aws_s3`/COPY TO, or a separate lower-cost Aurora/RDS instance) already provisioned and access-tested.
- DDL/DML privileges on the source table for the export and delete steps.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_confirm_archive_boundary.sql`](scripts/01_confirm_archive_boundary.sql) -- Confirms the exact row count and boundary that will be affected by the approved retention cutoff, before any data movement begins.
2. [`scripts/02_export_to_cold_storage.md`](scripts/02_export_to_cold_storage.md) -- Exports the to-be-archived rows to durable cold storage before any deletion, using batched, checkpointed exports.
3. [`scripts/03_validate_export_row_counts.sql`](scripts/03_validate_export_row_counts.sql) -- Compares the exported row count against the confirmed source scope from script 01.
4. [`scripts/04_spot_check_data_integrity.sql`](scripts/04_spot_check_data_integrity.sql) -- Spot-checks a sample of archived rows for full column-level integrity against the source, beyond just a row count match.
5. [`scripts/05_batched_deletion.md`](scripts/05_batched_deletion.md) -- Deletes the validated, archived rows from the source table in small, monitored batches -- the highest-risk step in this workflow.
6. [`scripts/06_post_archive_vacuum.sql`](scripts/06_post_archive_vacuum.sql) -- Checks dead tuple accumulation after the batched deletion and confirms whether a manual VACUUM is warranted to reclaim space.

## 8. Interpretation Guide

- Never delete before the export is independently validated (row counts, checksums, and ideally a spot-check restore/query against the archived copy) -- an archive is only as good as its untested restore path.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- N/A -- see the rollback/validation guidance in scripts 05-06 if an issue is found mid-process.

**Short-term remediation** (hours to days):

- N/A.

**Long-term engineering fix** (days to weeks):

- Once a table has a proven archive process, automate it on a recurring schedule (see retention-policy and automation/) rather than repeating this runbook manually each time.

## 10. Production Safety

- The batch DELETE step is the highest-risk part of this workflow -- it is provided as a guarded `.md` template, never a ready-to-run script, and must run in small, committed batches with monitoring, never as a single unbounded DELETE.
- Never DELETE before the corresponding export has been independently validated.
- Prefer PARTITION DETACH + archive-then-drop over row-level DELETE wherever the table is already partitioned by a compatible boundary -- it is dramatically faster and lower-risk (see archive-partition).

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Any validation step fails (exported row count does not match source) -- halt immediately and do not proceed to deletion; escalate to database engineering.
- The retention boundary is later found to conflict with an active legal hold or audit -- escalate to legal/compliance immediately and pause the archive process.

## 12. Related Issues

- [investigate-archiving-candidate](../investigate-archiving-candidate/README.md)
- [archive-partition](../archive-partition/README.md)
- [archive-validation](../archive-validation/README.md)
- [purge-old-data](../purge-old-data/README.md)
