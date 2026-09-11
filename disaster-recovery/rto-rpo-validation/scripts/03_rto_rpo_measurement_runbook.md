# 03_rto_rpo_measurement_runbook

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `03_rto_rpo_measurement_runbook.md` |
| Purpose | AWS-side guidance for the recovery-window figures the database cannot report, and the procedure for measuring real RTO during the drills in this category. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Any instance (writer or reader) |
| Safety | INFORMATIONAL -- NO SQL EXECUTED, AWS CONSOLE/API GUIDANCE ONLY |
| Expected impact | None. Every command shown is a read-only AWS describe call; no recovery action is triggered by this file. |
| Required privileges | IAM permission for rds:DescribeDBClusters, rds:DescribeGlobalClusters, and rds:DescribeDBClusterSnapshots; CloudWatch read access for the replication lag metric. No PostgreSQL role is used. |
| Prerequisites | Full read-only investigation for this workflow completed; maintenance window and second engineer approval obtained. |
| Execution order | Step 03 of workflow `disaster-recovery/rto-rpo-validation` |
| Related scripts | 01_observable_recovery_point_signals.sql, 02_recovery_reference_point.sql, 04_recovery_objectives_register.md |

## How to interpret / use this runbook

Measure RTO across the full chain from decision to customer-serving traffic, and measure RPO per scenario rather than once for the cluster -- a single unqualified pair of numbers is the most common way a DR policy ends up describing a capability the platform does not have.

---

This file documents AWS control-plane queries and a measurement procedure. Nothing here is executed against the database, and none of it triggers a recovery action.

## 1. The figures that actually bound your recovery point

```
aws rds describe-db-clusters \
  --db-cluster-identifier <cluster-identifier> \
  --query 'DBClusters[0].[BackupRetentionPeriod,EarliestRestorableTime,LatestRestorableTime,PreferredBackupWindow]'
```

`LatestRestorableTime` is typically within a few minutes of now -- the gap between it and the current time is the in-region recovery point for a PITR restore. `EarliestRestorableTime` and `BackupRetentionPeriod` together define how far back recovery is possible at all, which is the constraint that matters when an incident is discovered days after it started (a slow-burn data corruption, for example).

## 2. Cross-region recovery point

If an Aurora Global Database secondary exists, its replication lag is the cross-region recovery point, and it is usually sub-second to low-second:

```
aws rds describe-global-clusters \
  --global-cluster-identifier <global-cluster-identifier>
```

The `AuroraGlobalDBReplicationLag` CloudWatch metric is the figure to record over time rather than a single reading.

If there is no Global Database, the cross-region recovery point is the age of the most recent cross-region snapshot copy, which is normally measured in hours:

```
aws rds describe-db-cluster-snapshots \
  --region <dr-region> \
  --query 'DBClusterSnapshots[].[DBClusterSnapshotIdentifier,SnapshotCreateTime,Status]'
```

State this clearly in the DR policy: for most clusters without a Global Database, the regional-event recovery point is hours, not minutes, regardless of how good the in-region figures look.

## 3. Measuring real recovery time

Measure RTO during the drills already scheduled in this category rather than as a separate exercise. For each drill, record these timestamps:

| Marker | What it captures |
| --- | --- |
| T0 | The moment the recovery decision is made (not the moment the incident began) |
| T1 | The recovery action is initiated (failover triggered, restore submitted) |
| T2 | The database is accepting connections |
| T3 | Data validation has passed |
| T4 | The application is serving customer traffic correctly |

Measured RTO is T4 minus T0. Reporting T2 minus T1 as the RTO -- which is the number the AWS console most readily shows -- understates real recovery time, often by a wide margin, because it excludes decision time, instance provisioning, validation, and connection pool warm-up.

For a restore-based recovery, instance provisioning after the cluster restore is frequently the largest single component of T2 minus T1, and it scales with the instance class you choose to restore onto -- so a drill performed on a small scratch instance does not evidence the RTO of a production-sized recovery.

## 4. Measuring the observed recovery point

Run `02_recovery_reference_point.sql` on the source cluster before the drill and on the recovered/restored cluster afterward. The difference between the two `reference_timestamp` values, corroborated by the `xact_commit` delta, is the observed recovery point for that specific recovery path -- an actual measurement rather than the theoretical figure from step 1.

## 5. Scenario matrix

Record RTO and RPO separately per scenario, because a single pair of numbers for the whole cluster is always wrong for at least one of them:

| Scenario | Mechanism | Typical RTO | Typical RPO |
| --- | --- | --- | --- |
| Writer instance failure | Automatic failover to a reader | Under a minute | Effectively none |
| Planned maintenance reboot | Rolling reboot or blue/green switchover | Minutes, or seconds for blue/green | None |
| Logical data corruption | PITR restore into a new cluster | Tens of minutes plus validation | Minutes, bounded by LatestRestorableTime |
| Full cluster loss in region | Snapshot or PITR restore | Tens of minutes to hours | Minutes to hours |
| Regional event, Global Database present | Managed planned or unplanned failover | Minutes | Sub-second to seconds |
| Regional event, no Global Database | Cross-region snapshot copy restore | Hours | Hours |

Replace every figure in this table with your own measured results as drills produce them -- the table is a structure to fill in, and typical industry figures are not evidence for this cluster.
