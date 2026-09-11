# 04_recovery_objectives_register

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `04_recovery_objectives_register.md` |
| Purpose | The standing register: how to record each drill's measured results against the documented business targets so gaps stay visible between drills. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Any instance (writer or reader) |
| Safety | DOCUMENTATION -- no SQL executed by this file itself |
| Expected impact | None from this file directly; the drills it records results from carry their own impact, documented in their own workflows. |
| Required privileges | N/A for this file itself. |
| Prerequisites | Full read-only investigation for this workflow completed; maintenance window and second engineer approval obtained. |
| Execution order | Step 04 of workflow `disaster-recovery/rto-rpo-validation` |
| Related scripts | 03_rto_rpo_measurement_runbook.md, ../cluster-failover-drill/README.md, ../snapshot-restore-testing/README.md |

## How to interpret / use this runbook

Keep one register for the whole cluster and update it at every drill -- the value is in the trend and in the visibly-unmeasured scenarios, not in any single entry.

---

## Why a register rather than a drill report

Individual drill reports get filed and forgotten. A single register, updated after every drill, makes two things visible that no single report can: whether the measured figures are drifting as the dataset grows, and which scenarios have never actually been measured at all.

## What to record per entry

1. Scenario (use the scenario matrix in `03_rto_rpo_measurement_runbook.md`).
2. Documented business target for RTO and RPO for that scenario.
3. Measured RTO, broken down into the T0-T4 markers so the dominant component is visible rather than hidden in a single total.
4. Measured recovery point, from the before/after comparison of `02_recovery_reference_point.sql`.
5. Dataset size and instance class at the time of the drill -- without these the measurement cannot be compared against a later one.
6. Gap against target, stated explicitly as a number, including when it is comfortably within target.
7. Owner and due date for any remediation the gap implies.

## Cadence

- Failover scenario: measured at every `cluster-failover-drill`, quarterly at minimum.
- Restore scenarios: measured at every `backup-and-restore-validation`, `point-in-time-recovery-drill`, and `snapshot-restore-testing` exercise.
- Regional scenario: measured at whatever cadence the cross-region readiness review runs, and at minimum annually, since it is the scenario most likely to be assumed rather than tested.

## Re-measure when any of these change

- Data volume grows by an order of magnitude (restore time scales with it).
- Instance class or cluster topology changes.
- Backup retention or cross-region copy cadence changes.
- The application's connection handling or pool configuration changes, since that affects the T2-to-T4 portion that drills most often ignore.

## A measurement is only evidence if it is reproducible

Record enough detail that a different engineer could repeat the drill and get a comparable number: which endpoint was used, which instance class, what validation was run, and who made the T0 decision. An RTO figure with no recorded method is an assertion, and an assertion is exactly what this workflow exists to replace.
