# Snapshot Restore Testing

**Category:** Disaster Recovery | **Workflow:** `disaster-recovery/snapshot-restore-testing`

## 1. Problem Description

Proves that a specific manual or automated DB cluster snapshot can actually be restored into a working, correct cluster -- the narrower, snapshot-specific counterpart to backup-and-restore-validation's broader backup-configuration review and to point-in-time-recovery-drill's continuous-backup path. It covers fingerprinting the source cluster's contents, restoring the snapshot into an isolated scratch cluster, validating the restored database against that fingerprint, and decommissioning the scratch environment afterward.

## 2. Typical Symptoms

- A manual snapshot is taken before every major release or migration, but no snapshot has ever actually been restored, so the rollback plan is untested.
- An encrypted snapshot or a cross-account/cross-region snapshot copy exists and nobody has confirmed the restoring account or region has the KMS key access needed to use it.
- A snapshot restore was attempted during a real incident and stalled on a missing parameter group, subnet group, or security group that nobody had prepared.

## 3. Business Impact

- A snapshot that cannot be restored provides zero protection while creating the belief that protection exists -- for an exchange holding customer funds and ledger history, that belief is the risk, not the snapshot itself.
- Most snapshot restores are attempted for the first time under incident pressure, where a missing KMS grant or subnet group converts a bounded rollback into an extended outage.
- Testing the restore also produces the measured restore-duration evidence that the platform's RTO figure depends on (see rto-rpo-validation).

## 4. Possible Root Causes

- N/A -- this is a validation workflow. Where a restore fails, the cause is typically an AWS configuration gap (KMS key policy, subnet group, parameter group, security group, instance class availability) rather than a database-level fault.

## 5. Investigation Strategy

1. Fingerprint the source cluster before the test: object inventory, per-table row estimates and sizes, extension inventory, and key settings -- so 'the restore looks fine' can be replaced by a concrete comparison.
2. Restore the chosen snapshot into a new, isolated scratch cluster and provision at least one instance, since a cluster-level restore with no instance proves nothing.
3. Run the same fingerprint on the restored cluster and compare, then spot-check business-critical tables for recent, known rows.
4. Record the elapsed time for each phase, and decommission the scratch cluster immediately after validation.

## 6. Prerequisites

- pg_monitor role membership on the source cluster, and CONNECT plus pg_monitor on the restored scratch cluster for validation.
- IAM permission to describe and restore DB cluster snapshots and to create DB instances; for an encrypted snapshot, access to the KMS key (and, for a cross-account copy, a key policy that grants the restoring account access).
- A non-production VPC/subnet group and security group prepared in advance for the scratch cluster, so the restore is not blocked on networking setup.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_source_cluster_fingerprint.sql`](scripts/01_source_cluster_fingerprint.sql) -- Fingerprints the source cluster immediately before the snapshot restore test: object inventory, per-table row estimates and sizes, extensions, and key settings.
2. [`scripts/02_restored_cluster_validation.sql`](scripts/02_restored_cluster_validation.sql) -- Run on the restored scratch cluster: repeats the source fingerprint and adds engine identity and instance role, for a direct comparison against script 01.
3. [`scripts/03_snapshot_restore_runbook.md`](scripts/03_snapshot_restore_runbook.md) -- AWS-side guidance for selecting a snapshot, restoring it into an isolated scratch cluster, provisioning an instance, and tearing the environment down afterward.
4. [`scripts/04_restore_test_checklist.md`](scripts/04_restore_test_checklist.md) -- The ordered checklist for a snapshot restore test, including the business-data spot checks that a catalog-level fingerprint comparison cannot cover.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Aurora restores a DB cluster snapshot into a brand-new cluster with a new endpoint; the restore is never in place, and the restored cluster starts with no instances until you create at least one. An encrypted snapshot restores into an encrypted cluster and requires access to the KMS key it was encrypted with, which is the single most common blocker for a cross-account or cross-region restore. The restored cluster also takes whatever parameter group you specify (or the default) rather than automatically inheriting the source cluster's, which is why the settings comparison in this workflow's validation script matters.

## 8. Interpretation Guide

- Row-count estimates from the catalog (reltuples) are sufficient for comparison and far cheaper than exact counts on a large cluster -- they are maintained by vacuum and analyze, so compare them as approximate figures and only fall back to an exact count on a specific table where the estimate comparison looks wrong.
- A restored cluster is always a new cluster with its own endpoint, and it does not inherit the source's parameter group automatically unless you specify it -- an unexplained settings difference between source and restored fingerprints usually means the restore used a default parameter group, which will also make any performance comparison against the source meaningless.
- The restored cluster's statistics views (pg_stat_database, pg_stat_all_tables) start from the restore, not from the source's history, so xact_commit and scan counters will not match the source and are not a defect.
- A restore that completes but produces an instance stuck in a non-available state is usually a capacity or configuration problem in the target subnet/AZ, not a snapshot integrity problem -- read the event log before concluding the snapshot is bad.
- Restore duration scales with data volume and with the instance class chosen; a test restore onto a small instance class does not evidence the recovery time of a production-sized restore.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- N/A -- this is a planned validation exercise. If a restore fails during the test, that failure is the finding, and resolving it before an incident needs the snapshot is the work.

**Short-term remediation** (hours to days):

- Fix whatever blocked the restore (KMS key policy, subnet group, parameter group, security group, service quota) and re-run the test to confirm the fix, rather than recording the blocker and moving on.
- Decommission every scratch cluster and instance created during testing -- a forgotten scratch cluster is both an ongoing cost and, because it contains real customer and ledger data, a genuine security exposure.

**Long-term engineering fix** (days to weeks):

- Make a snapshot restore test part of the standing DR cadence and part of the release process for any migration whose rollback plan depends on a snapshot.
- Pre-create and document the scratch VPC, subnet group, security group, and parameter group used for restore testing, so a real incident restore does not have to create them under pressure.
- Automate the restore test (scheduled restore into an isolated account, automated fingerprint comparison, automatic teardown) so it runs without depending on somebody remembering.

## 10. Production Safety

- Every SQL script in this workflow is strictly read-only, on both the source and the restored cluster.
- The restore itself creates a new, separate cluster: it never modifies, replaces, or risks the production cluster, and it cannot be performed in place.
- The restored scratch cluster contains real production data -- customer balances, ledger entries, personally identifiable information -- so it must be created in an access-controlled environment, never pointed at by an application, and deleted promptly after validation.
- Never restore a snapshot into a cluster that reuses a production identifier, security group, or endpoint naming convention that an application could accidentally resolve.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- A snapshot fails to restore for any reason -- escalate immediately and treat the rollback plan that depended on it as invalid until a successful restore is demonstrated.
- The restored cluster's fingerprint differs from the source in ways that are not explained by the time gap between the snapshot and the fingerprint -- escalate to AWS Support and to the platform and compliance owners, since this calls actual data recoverability into question.
- The measured restore duration substantially exceeds the documented RTO for the restore scenario -- escalate through rto-rpo-validation as a policy gap.

## 12. Related Issues

- [backup-and-restore-validation](../backup-and-restore-validation/README.md)
- [point-in-time-recovery-drill](../point-in-time-recovery-drill/README.md)
- [rto-rpo-validation](../rto-rpo-validation/README.md)
- [cluster-failover-drill](../cluster-failover-drill/README.md)
- [comprehensive-health-check](../../database-health/comprehensive-health-check/README.md)
