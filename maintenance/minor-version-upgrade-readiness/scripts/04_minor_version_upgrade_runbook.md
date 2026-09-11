# 04_minor_version_upgrade_runbook

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `04_minor_version_upgrade_runbook.md` |
| Purpose | AWS-side guidance for executing the minor version upgrade itself, including the blue/green alternative for minimizing the interruption. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Any instance (writer or reader) |
| Safety | INFORMATIONAL -- NO SQL EXECUTED, AWS CONSOLE/API GUIDANCE ONLY |
| Expected impact | None from this file itself. The described in-place upgrade reboots every instance and terminates every connection; the blue/green switchover interrupts connections for a much shorter, bounded period. |
| Required privileges | IAM permission for rds:ModifyDBCluster, rds:DescribeDBEngineVersions, and (for blue/green) rds:CreateBlueGreenDeployment and rds:SwitchoverBlueGreenDeployment. No PostgreSQL role is used to trigger the upgrade. |
| Prerequisites | Full read-only investigation for this workflow completed; maintenance window and second engineer approval obtained. |
| Execution order | Step 04 of workflow `maintenance/minor-version-upgrade-readiness` |
| Related scripts | 01_current_engine_version_inventory.sql, 05_post_upgrade_validation_runbook.md, ../../disaster-recovery/cluster-failover-drill/README.md |

## How to interpret / use this runbook

Choose between in-place and blue/green on the basis of how long the platform can actually be down, not on setup convenience -- and treat the AWS release notes for every intermediate version as required reading, since the minor version gap is where behavior changes accumulate.

---

This file documents an AWS control-plane procedure. Nothing here is executed against the database by this repository, and none of it is a SQL statement -- an Aurora engine upgrade cannot be triggered from inside PostgreSQL.

## Before the window

1. Run `01_current_engine_version_inventory.sql`, `02_upgrade_blockers_precheck.sql`, and `03_extension_and_settings_upgrade_surface.sql`, and attach their output to the change ticket.
2. Confirm a recent backup is genuinely restorable -- not merely that a snapshot exists (see `disaster-recovery/backup-and-restore-validation`).
3. Confirm the target version is available for this cluster:

```
aws rds describe-db-engine-versions \
  --engine aurora-postgresql \
  --engine-version <current-engine-version> \
  --query "DBEngineVersions[].ValidUpgradeTarget[].[EngineVersion,IsMajorVersionUpgrade]"
```

4. Read the AWS release notes for every version between the current one and the target, not just the target's own notes.

## Option A: in-place upgrade (simplest, reboots the cluster)

```
aws rds modify-db-cluster \
  --db-cluster-identifier <cluster-identifier> \
  --engine-version <target-engine-version> \
  --apply-immediately
```

Omit `--apply-immediately` to defer the change to the cluster's next scheduled maintenance window. Every instance is rebooted and every connection is terminated; applications must reconnect exactly as they would during a failover, which is why `disaster-recovery/cluster-failover-drill` is the best rehearsal for this interruption.

## Option B: blue/green deployment (shorter interruption, more setup)

An RDS blue/green deployment creates a synchronized green environment already running the target engine version, letting you validate it before a switchover that is typically far shorter than an in-place upgrade's reboot:

```
aws rds create-blue-green-deployment \
  --blue-green-deployment-name <deployment-name> \
  --source <source-cluster-arn> \
  --target-engine-version <target-engine-version>
```

Validate the green environment (run this workflow's scripts 01 and 03 against it, plus the relevant application smoke tests) and only then switch over:

```
aws rds switchover-blue-green-deployment \
  --blue-green-deployment-identifier <deployment-identifier> \
  --switchover-timeout 300
```

For an exchange where order entry and withdrawal processing cannot absorb a multi-minute reboot during active trading hours, the extra setup cost of blue/green usually pays for itself in interruption length alone.

## Disable surprise upgrades while you are planning

If auto minor version upgrade is enabled, AWS may apply a minor version during the maintenance window on its own schedule. Decide deliberately which behavior you want; check it with:

```
aws rds describe-db-instances \
  --db-instance-identifier <instance-identifier> \
  --query "DBInstances[].AutoMinorVersionUpgrade"
```

## Immediately after the switchover or reboot

Re-run script 01 to confirm the new version, then follow `05_post_upgrade_validation_runbook.md` for the statistics refresh and extension updates -- an upgrade is not finished at the moment the cluster accepts connections again.
