# 02_point_in_time_recovery_runbook

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `02_point_in_time_recovery_runbook.md` |
| Purpose | Guarded runbook for restoring the cluster to a specific point in time into a new cluster, using the target time identified by script 01. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Any instance (writer or reader) |
| Safety | LOW RISK WRITE (creates a new, separate cluster; does not modify the existing cluster in place) |
| Expected impact | No impact to the existing production cluster; creates temporary AWS infrastructure cost for the recovery cluster until it is decommissioned. |
| Required privileges | AWS IAM permission to restore/create a new DB cluster and instance from a point in time; no elevated PostgreSQL privilege needed beyond CONNECT on the recovery cluster for validation. |
| Prerequisites | Full read-only investigation for this workflow completed; maintenance window and second engineer approval obtained. |
| Execution order | Step 02 of workflow `disaster-recovery/point-in-time-recovery-drill` |
| Related scripts | 01_target_restore_time_reference.sql |

## How to interpret / use this runbook

Confirm the retention window before restoring, and treat the recovery cluster strictly as a reference/source for reconciliation, never as a replacement for the live cluster.

---

## Confirm the target time is within the retention window

```
aws rds describe-db-clusters \
  --db-cluster-identifier <cluster-identifier> \
  --query 'DBClusters[0].[EarliestRestorableTime,LatestRestorableTime]'
```

The `suggested_restore_target_time` from script 01 must fall between these two timestamps -- if it does not, the required recovery point has already aged out of the configured backup retention period and cannot be restored via PITR.

## Restoring to the target time

This always creates a **new** cluster; it never modifies the existing one in place:

```
aws rds restore-db-cluster-to-point-in-time \
  --source-db-cluster-identifier <cluster-identifier> \
  --db-cluster-identifier <recovery-cluster-identifier> \
  --restore-to-time <suggested_restore_target_time-from-script-01> \
  --restore-type full-copy
```

Then provision at least one DB instance in the new cluster -- the cluster-level restore alone is not queryable until an instance exists in it.

## Validating and recovering the data

1. Connect to the recovery cluster's instance and confirm the restored data reflects the pre-incident state (spot-check the specific rows/tables known to be affected).
2. Identify exactly what needs to be corrected in production by comparing the recovery cluster against production -- do not treat the recovery cluster as an automatic drop-in replacement.
3. Perform a targeted, reviewed correction against production (e.g. re-inserting specific rows, or exporting a table's pre-incident state for reconciliation), with a second engineer reviewing the exact statements before they run against production.

## After the drill/incident

Decommission the recovery cluster once the correction is complete and confirmed, to avoid ongoing cost, and record the actual end-to-end time taken (time to identify the target time, restore duration, validation, and correction) for the next drill cycle.

## Do NOT

- Do NOT restore in-place or attempt to point the production application at the recovery cluster -- it exists solely to recover specific data, not to replace the running cluster.
- Do NOT skip the retention-window confirmation step -- requesting a restore-to-time outside `EarliestRestorableTime`/`LatestRestorableTime` will simply fail, and it is faster to confirm the window first than to discover the failure mid-incident.
