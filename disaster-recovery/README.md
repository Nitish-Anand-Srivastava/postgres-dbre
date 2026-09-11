# Disaster Recovery

Aurora-native recovery and continuity workflows for scenarios beyond normal
operational incident response: planned/tested failover, backup validation,
point-in-time recovery, and worst-case full-cluster or regional loss. Unlike
most of this repository, the actual recovery *actions* in this category are
AWS control-plane operations (`aws rds failover-db-cluster`, snapshot
restore, cross-region copy) rather than SQL statements -- Aurora manages
storage, replication, and recovery outside the database engine itself, so
these are documented as guarded runbooks with a companion read-only SQL
script (where one adds value) to gather the pre-/post-action state needed
to execute the runbook safely.

## Workflows

| Workflow | Summary |
| --- | --- |
| [`cluster-failover-drill`](cluster-failover-drill/README.md) | Planned failover drill: pre-checks, how Aurora failover actually works (reader promotion + endpoint re-point, not a restore), and post-failover verification. |
| [`backup-and-restore-validation`](backup-and-restore-validation/README.md) | Verifying automated backups/snapshots exist and periodically test-restoring into a scratch cluster. |
| [`point-in-time-recovery-drill`](point-in-time-recovery-drill/README.md) | Aurora's continuous-backup PITR model: restoring to any point within the retention window into a new cluster, and identifying the correct target time/LSN. |
| [`cross-region-and-full-cluster-loss`](cross-region-and-full-cluster-loss/README.md) | The worst-case scenario: Aurora Global Database regional failover, or restoring a full cluster from a cross-region snapshot copy. |

## Related categories

* [`replication-and-ha/failover-readiness`](../replication-and-ha/failover-readiness/README.md) -- day-to-day replication/lag/failover-readiness investigation that feeds into a failover decision.
* [`database-health/post-maintenance-check`](../database-health/post-maintenance-check/README.md) -- the verification workflow run after a failover or restore completes.
* [`incident-response/database-unavailable`](../incident-response/database-unavailable/README.md) -- the active-outage triage checklist that may lead here for a formal failover/restore decision.
