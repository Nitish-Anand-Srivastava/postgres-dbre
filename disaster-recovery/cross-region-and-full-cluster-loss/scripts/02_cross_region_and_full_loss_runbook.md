# 02_cross_region_and_full_loss_runbook

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `02_cross_region_and_full_loss_runbook.md` |
| Purpose | Guarded runbook covering both recovery paths for a true regional-scale event: Aurora Global Database managed failover, and cross-region snapshot-copy restore when no Global Database is in place. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Any instance (writer or reader) |
| Safety | ELEVATED RISK (regional-scale recovery action -- either promotes a secondary region as the new production primary, or restores a new cluster from a potentially-hours-old cross-region snapshot copy) |
| Expected impact | A managed Global Database failover accepts a small (sub-second to low-single-digit-second) data-loss window; a snapshot-copy restore accepts a data-loss window bounded by the copy schedule's frequency, typically much larger. |
| Required privileges | AWS IAM permission for rds:FailoverGlobalCluster (Path A) or rds:RestoreDBClusterFromSnapshot in the target region (Path B); no PostgreSQL role is used to trigger either recovery path. |
| Prerequisites | Full read-only investigation for this workflow completed; maintenance window and second engineer approval obtained. |
| Execution order | Step 02 of workflow `disaster-recovery/cross-region-and-full-cluster-loss` |
| Related scripts | 01_pre_incident_baseline_reference.sql |

## How to interpret / use this runbook

Escalate to full incident command immediately for any true regional event -- this runbook exists to make the mechanical recovery steps fast and correct once that escalation has happened, not to substitute for it.

---

## First, determine which recovery path applies

Confirm in advance (this cannot be determined mid-event from inside a lost/unreachable region) whether this cluster is part of an Aurora Global Database (managed cross-region replication already in place) or relies solely on cross-region-copied snapshots. The two paths below are not interchangeable.

## Path A -- Aurora Global Database failover

```
aws rds failover-global-cluster \
  --global-cluster-identifier <global-cluster-identifier> \
  --target-db-cluster-identifier <secondary-region-cluster-arn>
```

This promotes the named secondary-region cluster to become the new primary of the global cluster. Because Global Database replication is asynchronous, the most recent sub-second-to-low-single-digit-seconds of committed writes on the original primary may not have replicated and will not be present after failover -- this is an accepted characteristic of the mechanism (see this workflow's Aurora Notes), not a failure of the failover itself.

## Path B -- restore from a cross-region snapshot copy

If no Global Database exists (or it is also affected), identify the most recent valid snapshot copy already present in a healthy target region:

```
aws rds describe-db-cluster-snapshots \
  --region <target-region> \
  --snapshot-type manual \
  --query 'DBClusterSnapshots[].[DBClusterSnapshotIdentifier,SnapshotCreateTime,Status]'
```

Then restore it into a new cluster in that region:

```
aws rds restore-db-cluster-from-snapshot \
  --region <target-region> \
  --db-cluster-identifier <recovery-cluster-identifier> \
  --snapshot-identifier <most-recent-valid-snapshot-identifier> \
  --engine aurora-postgresql
```

Then provision at least one DB instance in the new cluster. This path's RPO is bounded by the snapshot-copy schedule's frequency, typically far coarser than Global Database's near-real-time replication -- communicate the actual data-loss window implied by the restored snapshot's timestamp to stakeholders explicitly.

## After either path

1. Re-run `01_pre_incident_baseline_reference.sql` against the new primary/recovered cluster and compare against the reference captured beforehand.
2. Update application configuration/DNS to point at the new region's endpoint.
3. Communicate the accepted data-loss window to stakeholders and begin reconciling any transactions known to have been in flight at the time of the event.
4. Once stable, evaluate re-establishing cross-region replication/backup-copy coverage from the new primary region, since the original topology's protection is gone until it is rebuilt.

## Do NOT

- Do NOT assume Path A (Global Database failover) is available without having confirmed in advance that this specific cluster is part of a Global Database -- attempting it against a cluster that is not will simply fail and cost time you do not have during a true regional event.
- Do NOT skip communicating the RPO/data-loss window to stakeholders once the recovery path is chosen -- the business, not the DBA alone, must decide how to handle the transactions that fall within that window.
