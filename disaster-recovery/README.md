# Disaster Recovery

**Category:** `disaster-recovery`

This is the index for the `disaster-recovery/` category: every workflow
(issue directory) below addresses a distinct, real operational problem or
DBA use case for this Aurora PostgreSQL toolkit, per the repository's
one-parent-directory-per-problem design. Each workflow directory is
self-contained -- its own `README.md` (problem description, symptoms,
business impact, root causes, investigation strategy, prerequisites,
interpretation guide, remediation options, production safety, and
escalation criteria) and a `scripts/` directory of numbered, read-only-by
-default investigation scripts (see each workflow's `scripts/README.md`
for the full script-by-script execution table).

## Workflows

| Workflow | Summary |
| --- | --- |
| [`cluster-failover-drill`](cluster-failover-drill/README.md) | A planned, deliberately triggered failover of the Aurora cluster to validate that the reader fleet, application connection handling, and operational runbooks all behave as expected -- run proactively, on a schedule, rather than waiting to learn the answer during an unplanned failover. |
| [`backup-and-restore-validation`](backup-and-restore-validation/README.md) | Verifies that Aurora's automated backups/snapshots actually exist within the expected retention window, and periodically proves they are restorable by test-restoring into a scratch cluster -- since an untested backup is only a assumption, not a verified recovery capability. |
| [`point-in-time-recovery-drill`](point-in-time-recovery-drill/README.md) | Plans and practices restoring the cluster to a specific point in time within Aurora's continuous backup retention window -- always into a new cluster, never in-place -- for the scenario where a specific past moment (just before a bad deployment or an erroneous bulk write) needs to be recovered to, rather than only the latest restorable time. |
| [`cross-region-and-full-cluster-loss`](cross-region-and-full-cluster-loss/README.md) | Covers the worst-case disaster scenarios beyond a single-cluster failover: a regional-scale event handled via Aurora Global Database's cross-region failover, or the total, unrecoverable loss of the primary cluster requiring restore from a cross-region-copied snapshot into an entirely new region -- fundamentally an AWS infrastructure recovery process, not a SQL-level investigation. |
| [`rto-rpo-validation`](rto-rpo-validation/README.md) | Turns the recovery time objective and recovery point objective written in the platform's DR policy into measured, evidenced numbers rather than assumptions. It covers what the database itself can tell you about potential data loss (reader lag, logical replication slot lag, the restorable-time window), how to measure real recovery time during the drills in this category, and how to record the result against the business target so a gap is visible before an incident proves it. |
| [`snapshot-restore-testing`](snapshot-restore-testing/README.md) | Proves that a specific manual or automated DB cluster snapshot can actually be restored into a working, correct cluster -- the narrower, snapshot-specific counterpart to backup-and-restore-validation's broader backup-configuration review and to point-in-time-recovery-drill's continuous-backup path. It covers fingerprinting the source cluster's contents, restoring the snapshot into an isolated scratch cluster, validating the restored database against that fingerprint, and decommissioning the scratch environment afterward. |

## Related Categories

- [`database-health/comprehensive-health-check`](../../database-health/comprehensive-health-check/README.md)
- [`database-health/post-maintenance-check`](../../database-health/post-maintenance-check/README.md)
- [`maintenance/routine-maintenance-checklist`](../../maintenance/routine-maintenance-checklist/README.md)
- [`performance/performance-after-failover`](../../performance/performance-after-failover/README.md)
- [`replication-and-ha/failover-investigation`](../../replication-and-ha/failover-investigation/README.md)
- [`replication-and-ha/failover-readiness`](../../replication-and-ha/failover-readiness/README.md)
- [`replication-and-ha/replication-health`](../../replication-and-ha/replication-health/README.md)

Start with the workflow whose title most closely matches the symptom you are
investigating; if uncertain, `database-health/comprehensive-health-check`
and `incident-response/production-triage` both provide a broad first pass
that surfaces which specific workflow to open next.
