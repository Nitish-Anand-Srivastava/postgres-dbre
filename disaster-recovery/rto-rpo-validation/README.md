# RTO and RPO Validation

**Category:** Disaster Recovery | **Workflow:** `disaster-recovery/rto-rpo-validation`

## 1. Problem Description

Turns the recovery time objective and recovery point objective written in the platform's DR policy into measured, evidenced numbers rather than assumptions. It covers what the database itself can tell you about potential data loss (reader lag, logical replication slot lag, the restorable-time window), how to measure real recovery time during the drills in this category, and how to record the result against the business target so a gap is visible before an incident proves it.

## 2. Typical Symptoms

- The DR policy states an RTO and RPO but nobody can point to a measurement that demonstrates either is actually achievable on this cluster.
- A failover or restore drill was performed but its duration was never recorded, so the RTO figure in the policy is still an estimate.
- A logical replication consumer (a CDC pipeline feeding the data warehouse, risk engine, or compliance archive) is lagging, and nobody has quantified what that means for downstream recovery point.

## 3. Business Impact

- For a crypto exchange, RPO is measured in trades and ledger entries, not abstract seconds: an unmeasured recovery point means an unknown number of order fills, deposits, and withdrawals could be unrecoverable, which is a customer-funds and regulatory reporting problem rather than only a technical one.
- An RTO that turns out to be several times the documented figure converts a controlled recovery into a prolonged trading outage, with market-maker and venue-reputation consequences that scale with the duration.
- Regulators and auditors of a regulated venue generally expect evidenced recovery capability, not a policy document alone -- measured drill results are that evidence.

## 4. Possible Root Causes

- N/A -- this is a validation and evidence workflow. Where a measurement misses its target, the cause belongs to the underlying mechanism (backup retention configuration, failover behavior, instance provisioning time, a lagging replication consumer) and is investigated in that mechanism's own workflow.

## 5. Investigation Strategy

1. Establish what the database can observe about potential data loss right now: reader lag, logical slot lag and retained WAL, and the current recovery reference point.
2. Establish what the AWS control plane reports about the restorable window (earliest and latest restorable time), since that -- not anything queryable in SQL -- defines the actual PITR boundary.
3. Measure real recovery time during the drills already in this category (cluster-failover-drill, backup-and-restore-validation, point-in-time-recovery-drill) rather than performing a separate artificial exercise.
4. Compare each measurement against the documented business target and record the gap explicitly.

## 6. Prerequisites

- pg_monitor role membership for the read-only scripts; IAM permission to describe DB clusters for the restorable-window figures; the organization's documented RTO/RPO targets to measure against; drills from this category scheduled so measurements come from real exercises.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_observable_recovery_point_signals.sql`](scripts/01_observable_recovery_point_signals.sql) -- Captures every recovery-point signal the database itself can report: instance role, Aurora reader lag, and replication slot lag with retained WAL.
2. [`scripts/02_recovery_reference_point.sql`](scripts/02_recovery_reference_point.sql) -- Records a durable, engine-safe reference point (server time and commit counters, plus LSN only where supported) for comparing against a restored cluster after a drill.
3. [`scripts/03_rto_rpo_measurement_runbook.md`](scripts/03_rto_rpo_measurement_runbook.md) -- AWS-side guidance for the recovery-window figures the database cannot report, and the procedure for measuring real RTO during the drills in this category.
4. [`scripts/04_recovery_objectives_register.md`](scripts/04_recovery_objectives_register.md) -- The standing register: how to record each drill's measured results against the documented business targets so gaps stay visible between drills.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Aurora separates the two objectives across different mechanisms, and they must be measured separately: in-region instance failure is handled by promoting an existing reader on the same shared storage volume (seconds of RTO, effectively no data loss), while a regional event depends either on an Aurora Global Database secondary (typically sub-second to low-second replication lag, promotion in minutes) or on cross-region snapshot copies (recovery point measured in hours). Quoting a single cluster-wide RTO/RPO pair without saying which failure scenario it describes is the most common way these numbers end up wrong.

## 8. Interpretation Guide

- Aurora reader lag is typically milliseconds because readers share the same storage volume as the writer, so it is a poor proxy for RPO against a total cluster loss -- it describes read-after-write staleness for reader-endpoint traffic, which is an application-correctness concern, not a disaster recovery boundary.
- The figures that actually bound RPO are the backup retention window and the LatestRestorableTime reported by the AWS control plane (typically within minutes of now), plus, for cross-region scenarios, the Aurora Global Database replication lag or the age of the most recent cross-region snapshot copy -- which can be hours, and is usually the real RPO constraint for a regional event.
- Logical replication slot lag defines the recovery point for everything downstream of the database, not for the database itself: a lagging CDC consumer means the warehouse, risk, or compliance copy is behind, which matters for reconstructing state after an incident even when the database itself recovers cleanly.
- RTO is not the restore command's duration. It is wall-clock time from the decision to recover until the platform is serving customer traffic correctly, which includes provisioning instances, warming connection pools, validating data, and the human decision time that precedes all of it -- measure the whole chain or the number is not usable.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- N/A -- this is a measurement and evidence workflow. A measured gap against target is a finding to plan against, not an incident to remediate live.

**Short-term remediation** (hours to days):

- Record every drill's measured recovery time and observed recovery point in a single register alongside the business target, so the gap is a visible number rather than an impression.
- Where a logical slot is lagging materially, resolve it through replication-and-ha/replication-health before it becomes both a storage problem and a downstream recovery-point problem.

**Long-term engineering fix** (days to weeks):

- Close a measured RTO gap with the mechanism that actually addresses it: pre-provisioned reader capacity and rehearsed failover for short RTOs, an Aurora Global Database for cross-region RTO/RPO, blue/green for upgrade-related interruption.
- Increase backup retention, or add more frequent cross-region snapshot copies, where the measured recovery point boundary is wider than the policy allows.
- Re-measure after any change to instance class, cluster topology, or data volume -- an RTO measured against a dataset a fraction of the current size is no longer evidence.

## 10. Production Safety

- Every SQL script in this workflow is strictly read-only and safe to run against production at any time.
- This workflow triggers no recovery action of its own -- the measurements come from drills defined in the other workflows in this category, each with its own safety notes.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- A measured recovery time or recovery point misses the documented business target by a material margin -- escalate to the platform and compliance owners, since the organization is operating against a DR policy it cannot currently meet.
- The cross-region recovery point (Global Database lag or cross-region snapshot copy age) is materially worse than the policy assumes and no Global Database is configured -- escalate as an architectural gap rather than an operational one.

## 12. Related Issues

- [cluster-failover-drill](../cluster-failover-drill/README.md)
- [backup-and-restore-validation](../backup-and-restore-validation/README.md)
- [point-in-time-recovery-drill](../point-in-time-recovery-drill/README.md)
- [snapshot-restore-testing](../snapshot-restore-testing/README.md)
- [replication-health](../../replication-and-ha/replication-health/README.md)
