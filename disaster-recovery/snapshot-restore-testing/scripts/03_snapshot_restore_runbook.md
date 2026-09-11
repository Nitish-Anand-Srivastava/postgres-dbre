# 03_snapshot_restore_runbook

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `03_snapshot_restore_runbook.md` |
| Purpose | AWS-side guidance for selecting a snapshot, restoring it into an isolated scratch cluster, provisioning an instance, and tearing the environment down afterward. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Any instance (writer or reader) |
| Safety | INFORMATIONAL -- NO SQL EXECUTED, AWS CONSOLE/API GUIDANCE ONLY |
| Expected impact | No impact on the production cluster -- a snapshot restore always creates a new cluster. Creates temporary AWS cost for the scratch cluster and instance until they are deleted. |
| Required privileges | IAM permission for rds:DescribeDBClusterSnapshots, rds:RestoreDBClusterFromSnapshot, rds:CreateDBInstance, rds:DeleteDBInstance, and rds:DeleteDBCluster; KMS key access for an encrypted snapshot. No PostgreSQL role is used for the restore itself. |
| Prerequisites | Full read-only investigation for this workflow completed; maintenance window and second engineer approval obtained. |
| Execution order | Step 03 of workflow `disaster-recovery/snapshot-restore-testing` |
| Related scripts | 01_source_cluster_fingerprint.sql, 02_restored_cluster_validation.sql, 04_restore_test_checklist.md |

## How to interpret / use this runbook

Restore into an isolated, access-restricted environment, specify the source parameter group explicitly, validate with script 02 before calling the test successful, and tear the scratch environment down the same day.

---

This file documents an AWS control-plane procedure. Nothing here is a SQL statement and nothing here modifies the production cluster -- an Aurora snapshot restore always creates a new cluster and can never overwrite an existing one.

## 1. Choose the snapshot to test

```
aws rds describe-db-cluster-snapshots \
  --db-cluster-identifier <cluster-identifier> \
  --query 'DBClusterSnapshots[].[DBClusterSnapshotIdentifier,SnapshotType,Status,SnapshotCreateTime,StorageEncrypted,KmsKeyId]'
```

Prefer testing the kind of snapshot your rollback plans actually depend on -- if releases are gated on a manual pre-release snapshot, test a manual snapshot, not an automated one. Note `StorageEncrypted` and `KmsKeyId`: if the snapshot is encrypted, the restoring principal needs access to that key, and for a cross-account copy the key policy must grant the restoring account access. This is the most common reason a first restore attempt fails.

## 2. Restore into an isolated scratch cluster

```
aws rds restore-db-cluster-from-snapshot \
  --db-cluster-identifier <scratch-cluster-identifier> \
  --snapshot-identifier <snapshot-identifier> \
  --engine aurora-postgresql \
  --db-subnet-group-name <non-production-subnet-group> \
  --vpc-security-group-ids <restricted-security-group-id> \
  --db-cluster-parameter-group-name <same-parameter-group-as-source>
```

Specify the source cluster's parameter group explicitly. If you omit it, the restored cluster uses the default group, and the settings comparison in script 02 will differ for reasons that have nothing to do with the snapshot.

Use a restricted security group that permits access only from the DBA bastion or equivalent. The restored cluster contains real customer balances and ledger history; it must not be reachable from anything that could treat it as a live environment.

## 3. Provision an instance -- the restore is not usable without one

```
aws rds create-db-instance \
  --db-instance-identifier <scratch-instance-identifier> \
  --db-cluster-identifier <scratch-cluster-identifier> \
  --engine aurora-postgresql \
  --db-instance-class <instance-class>
```

For a test whose purpose includes evidencing recovery time, use the same instance class as production -- a restore validated on a small instance class does not evidence the RTO of a production-sized recovery (see `rto-rpo-validation`).

## 4. Wait for availability and record the elapsed time

```
aws rds wait db-instance-available \
  --db-instance-identifier <scratch-instance-identifier>
```

Record the wall-clock time for the cluster restore and for instance provisioning separately -- provisioning is frequently the larger of the two, and knowing the split is what makes the measurement actionable.

If the instance does not reach `available`, read the events before blaming the snapshot:

```
aws rds describe-events \
  --source-identifier <scratch-instance-identifier> \
  --source-type db-instance \
  --duration 120
```

## 5. Validate

Connect to the restored cluster's writer endpoint and run `02_restored_cluster_validation.sql`, then work through `04_restore_test_checklist.md`.

## 6. Tear the scratch environment down

```
aws rds delete-db-instance \
  --db-instance-identifier <scratch-instance-identifier> \
  --skip-final-snapshot

aws rds delete-db-cluster \
  --db-cluster-identifier <scratch-cluster-identifier> \
  --skip-final-snapshot
```

Delete the instance first, then the cluster. Teardown is not optional housekeeping: a forgotten scratch cluster holding production data is a standing security exposure as well as an ongoing cost, and it is exactly the kind of environment that ends up outside the normal access review.

## Do NOT

- Do NOT point any application, job, or reporting tool at the scratch cluster.
- Do NOT reuse a production-like identifier or DNS name for it.
- Do NOT call the test successful at the point the cluster reaches `available` -- availability is not validation, and script 02 is what distinguishes them.
