# Point-in-Time Recovery (PITR) Drill

**Category:** Disaster Recovery | **Workflow:** `disaster-recovery/point-in-time-recovery-drill`

## 1. Problem Description

Plans and practices restoring the cluster to a specific point in time within Aurora's continuous backup retention window -- always into a new cluster, never in-place -- for the scenario where a specific past moment (just before a bad deployment or an erroneous bulk write) needs to be recovered to, rather than only the latest restorable time.

## 2. Typical Symptoms

- A bad deployment or an erroneous bulk UPDATE/DELETE corrupted data starting at a known point in time, and the fix requires recovering data as it existed just before that point.
- No active symptom -- run as a periodic drill (often alongside backup-and-restore-validation) to confirm the team can execute a PITR restore under time pressure before ever needing to.

## 3. Business Impact

- A real incident requiring PITR is, by definition, already a data-integrity emergency -- practicing the exact restore-to-time mechanics (identifying the right target time, running the restore, validating the result) in a drill removes the risk of fumbling the mechanism itself while under the added pressure of a live incident.

## 4. Possible Root Causes

- N/A for the drill itself; the scenario it prepares for is typically an application-level bug (a bad deployment or an erroneous bulk write) rather than a database-level fault.

## 5. Investigation Strategy

1. Identify the target restore-to time based on when the incident actually started (from application logs, deployment timestamps, or the first bad row's own timestamp column -- not solely from database-side signals, since the database itself usually has no record of *why* a write was wrong, only that it happened).
2. Restore to a point slightly before the identified incident start, into a new cluster, never in-place.
3. Validate the restored data represents the pre-incident state before using it for any recovery action (e.g. re-inserting lost-but-good rows into production).

## 6. Prerequisites

- AWS IAM permission to restore a new cluster from point-in-time; a reasonably precise incident-start timestamp (from application logs/deployment records) to restore against.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_target_restore_time_reference.sql`](scripts/01_target_restore_time_reference.sql) -- Given an operator-supplied suspected incident-start timestamp, computes a suggested restore-to target slightly earlier, alongside the current server time and WAL position for reference.
2. [`scripts/02_point_in_time_recovery_runbook.md`](scripts/02_point_in_time_recovery_runbook.md) -- Guarded runbook for restoring the cluster to a specific point in time into a new cluster, using the target time identified by script 01.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Aurora's continuous backup mechanism supports restoring to any second within the configured backup retention window (1-35 days) via restore-db-cluster-to-point-in-time, distinct from restoring from a specific named manual snapshot -- both restore into a new cluster, never in-place, which is a deliberate safety property of the mechanism, not a limitation to work around.

## 8. Interpretation Guide

- Aurora's PITR restore always creates a brand-new cluster as of the requested time -- it is never an in-place rollback of the existing cluster, which means the existing (post-incident) cluster keeps running throughout, and the restored cluster is a separate point of reference to compare against and selectively recover from, not a direct replacement.
- Restoring to a time slightly earlier than your best estimate of the incident start is safer than restoring to the exact estimated moment -- if the estimate is a little late, you still have the bad data in the restored copy; if it is well early, you can identify the correct cutover using the data itself once you have the restored cluster to inspect.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Restore into a new cluster at the identified target time, then use the restored cluster's data to identify and manually reconcile what needs to be corrected in production -- never restore in-place and never treat the restored cluster as an automatic drop-in replacement for the live cluster.

**Short-term remediation** (hours to days):

- Once the specific bad rows/tables are identified by comparing the restored cluster against production, perform a targeted, reviewed data-correction (not a blanket restore-and-replace) against production.

**Long-term engineering fix** (days to weeks):

- Feed the incident's actual timeline (how precisely the start time was identified, how long the restore took) back into this drill's practiced procedure, and add any missing tooling/logging that made identifying the target time harder than it should have been.

## 10. Production Safety

- The SQL companion script here is read-only and only assists in reasoning about a target time; it does not perform any restore itself. The restore itself creates a new, separate cluster and does not modify the existing cluster.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- The incident-start time cannot be identified with reasonable confidence from available logs/timestamps -- escalate to restore multiple candidate points in parallel (as separate scratch clusters) rather than guessing a single target time for a data-integrity-critical restore.

## 12. Related Issues

- [backup-and-restore-validation](../backup-and-restore-validation/README.md)
- [cluster-failover-drill](../cluster-failover-drill/README.md)
