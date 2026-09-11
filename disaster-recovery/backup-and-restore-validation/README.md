# Backup and Restore Validation

**Category:** Disaster Recovery | **Workflow:** `disaster-recovery/backup-and-restore-validation`

## 1. Problem Description

Verifies that Aurora's automated backups/snapshots actually exist within the expected retention window, and periodically proves they are restorable by test-restoring into a scratch cluster -- since an untested backup is only a assumption, not a verified recovery capability.

## 2. Typical Symptoms

- No active symptom -- a scheduled validation practice, typically run monthly or quarterly and ahead of any compliance review that requires evidence of tested backup/restore capability.
- Run reactively after any change to backup retention configuration to confirm the new setting took effect as intended.

## 3. Business Impact

- For a financial trading platform, 'we have automated backups' is not the same claim as 'we have confirmed we can actually restore from them' -- a backup that has never been test-restored can fail silently (a corrupted snapshot, an unexpectedly short retention window, a permissions issue on the target account) and that failure is only ever discovered during a real disaster, which is the worst possible time.

## 4. Possible Root Causes

- Backup retention period was reduced (intentionally or accidentally) below what the organization's recovery point objective actually requires.
- A backup/snapshot exists but has never been test-restored, so an unknown issue (permissions, corruption, cross-account/cross-region copy configuration) would only surface during an actual disaster.
- Continuous backup (which Aurora uses for PITR) is a distinct mechanism from manual/automated snapshots -- confirming one does not confirm the other.

## 5. Investigation Strategy

1. Confirm current backup retention configuration and snapshot existence via the AWS control plane (not SQL -- this information lives entirely outside PostgreSQL).
2. Capture a SQL-side reference snapshot (current WAL position and database-level statistics) immediately before a scheduled test-restore, to have a concrete before/after comparison point.
3. Perform the test-restore into a scratch cluster and validate the restored data against the reference snapshot.

## 6. Prerequisites

- AWS IAM permission to describe cluster snapshots/backup configuration and to restore into a new (scratch) cluster; a scratch-cluster budget/approval for periodic test restores, since this creates real (temporary) infrastructure.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_restore_point_reference_snapshot.sql`](scripts/01_restore_point_reference_snapshot.sql) -- Captures a SQL-side reference point (current WAL position and database-level statistics) immediately before a scheduled test-restore, for concrete before/after comparison.
2. [`scripts/02_backup_and_restore_test_runbook.md`](scripts/02_backup_and_restore_test_runbook.md) -- Guarded runbook for confirming backup/snapshot configuration via the AWS control plane and performing a periodic test-restore into a scratch cluster.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Aurora automatically and continuously backs up cluster storage to S3 in a way that supports point-in-time restore across the configured backup retention window (1-35 days), independent of any manual snapshot -- automated backups and manual DB cluster snapshots are complementary, not interchangeable: retention-window PITR capability should not be assumed to also mean a specific manual snapshot exists, and vice versa.

## 8. Interpretation Guide

- Automated backups and manual snapshots being present and within retention is necessary but not sufficient evidence of recoverability -- treat a clean test-restore, performed at least once per validation cycle, as the actual proof; existence of a snapshot alone is only evidence that the mechanism ran, not that the data is usable.
- The SQL-side reference snapshot (script 01) is a sanity/comparison aid, not the recovery point itself -- the actual recovery point for Aurora backups is managed and tracked entirely by the AWS control plane (backup window, retention period), which this workflow's runbook checks separately.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- N/A -- this is a proactive validation workflow, not an incident response; if validation reveals backups are NOT actually restorable, treat that finding itself as an urgent gap to close, even though nothing is actively broken yet.

**Short-term remediation** (hours to days):

- If backup retention is shorter than the organization's recovery point objective requires, increase it via the cluster's backup configuration.
- If a test-restore fails or reveals unexpected data loss/corruption, open an AWS Support case immediately -- this is exactly the failure mode this workflow exists to catch before a real disaster.

**Long-term engineering fix** (days to weeks):

- Establish a standing test-restore cadence (e.g. quarterly) with the scratch cluster's cost budgeted for in advance, and track each cycle's result (success/failure, time taken) as a compliance/audit artifact.

## 10. Production Safety

- The SQL scripts here are read-only. The test-restore itself creates a new, separate scratch cluster -- it does not modify or risk the production cluster in any way, and the scratch cluster should be decommissioned after validation to avoid ongoing cost.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- A scheduled test-restore fails, or the restored data does not match the pre-restore reference snapshot -- escalate to AWS Support and to the platform/compliance team immediately, since this means the organization's actual recovery capability does not match its assumed one.

## 12. Related Issues

- [cluster-failover-drill](../cluster-failover-drill/README.md)
- [point-in-time-recovery-drill](../point-in-time-recovery-drill/README.md)
- [routine-maintenance-checklist](../../maintenance/routine-maintenance-checklist/README.md)
