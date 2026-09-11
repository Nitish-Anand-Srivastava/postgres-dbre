# 02_backup_and_restore_test_runbook

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `02_backup_and_restore_test_runbook.md` |
| Purpose | Guarded runbook for confirming backup/snapshot configuration via the AWS control plane and performing a periodic test-restore into a scratch cluster. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Any instance (writer or reader) |
| Safety | LOW RISK WRITE (creates a new, separate scratch cluster; does not modify or risk the production cluster) |
| Expected impact | No impact to the production cluster; creates temporary AWS infrastructure cost for the scratch cluster until it is decommissioned. |
| Required privileges | AWS IAM permission to describe cluster/snapshot configuration and to restore/create a new DB cluster and instance; no elevated PostgreSQL privilege needed beyond CONNECT on the restored scratch cluster for validation. |
| Prerequisites | Full read-only investigation for this workflow completed; maintenance window and second engineer approval obtained. |
| Execution order | Step 02 of workflow `disaster-recovery/backup-and-restore-validation` |
| Related scripts | 01_restore_point_reference_snapshot.sql |

## How to interpret / use this runbook

Work through configuration confirmation first, then the actual test-restore, then validation against the reference snapshot -- treat a restore with no subsequent data validation as an incomplete drill.

---

## Confirm backup configuration exists and meets your retention requirement

```
aws rds describe-db-clusters \
  --db-cluster-identifier <cluster-identifier> \
  --query 'DBClusters[0].[BackupRetentionPeriod,PreferredBackupWindow,EarliestRestorableTime,LatestRestorableTime]'
```

Confirm `BackupRetentionPeriod` (in days) meets your organization's recovery point objective, and that `EarliestRestorableTime`/`LatestRestorableTime` span the window you expect.

## Confirm manual/automated snapshots exist

```
aws rds describe-db-cluster-snapshots \
  --db-cluster-identifier <cluster-identifier> \
  --query 'DBClusterSnapshots[].[DBClusterSnapshotIdentifier,SnapshotType,Status,SnapshotCreateTime]'
```

## Test-restoring into a scratch cluster

Restore into a **new**, separate cluster -- this never touches the production cluster:

```
aws rds restore-db-cluster-to-point-in-time \
  --source-db-cluster-identifier <cluster-identifier> \
  --db-cluster-identifier <scratch-cluster-identifier> \
  --use-latest-restorable-time
```

(Substitute `--restore-to-time <timestamp>` for `--use-latest-restorable-time` to validate an earlier point instead.) Then create at least one DB instance in the new scratch cluster so it is actually queryable -- a cluster restore alone does not provision a compute instance.

## Validating the restore

1. Connect to the scratch cluster's instance and re-run `01_restore_point_reference_snapshot.sql` there; compare against the reference captured on the source cluster.
2. Spot-check a handful of known recent rows/tables for presence and correctness.
3. Record the total restore time (snapshot/PITR restore plus instance provisioning) as part of your recovery-time-objective evidence.

## Cleaning up

Decommission the scratch cluster and its instance(s) after validation completes, to avoid ongoing cost -- this is a test-restore, not a standing environment.

## Do NOT

- Do NOT point any application at the scratch cluster -- it exists solely for validation and must never become a de facto second production environment.
- Do NOT skip provisioning at least one instance in the restored cluster and call the restore 'validated' -- a cluster-level restore with no instance to query proves nothing about actual data recoverability.
