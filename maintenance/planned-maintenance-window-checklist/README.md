# Planned Maintenance Window Checklist

**Category:** Maintenance | **Workflow:** `maintenance/planned-maintenance-window-checklist`

## 1. Problem Description

The wrapper procedure around any planned, disruptive maintenance on this cluster -- an engine upgrade, a reboot for a static parameter change, a failover drill, an instance class change, or a large schema migration. It defines what to verify before the window opens, what to hold as the go/no-go decision, and what to verify afterward before declaring the window closed and handing the platform back to trading.

## 2. Typical Symptoms

- A disruptive maintenance action is scheduled and the team wants a consistent, repeatable procedure rather than an ad hoc checklist assembled from memory each time.
- A previous window overran or left a change half-applied because a pre-check (a long-running transaction, an in-flight index build, a lagging reader) was not performed beforehand.
- Post-window, nobody could say definitively whether the platform was fully healthy or merely accepting connections again.

## 3. Business Impact

- For an exchange, a maintenance window is a deliberate, scheduled outage of order entry, deposits, and withdrawals -- overrunning it converts planned, communicated downtime into an incident with customer, market-maker, and regulatory consequences.
- A window closed prematurely, before the cluster is genuinely healthy, pushes the real failure into live trading hours where it is far more expensive.
- Consistent pre/post evidence for each window is also the operational audit trail a regulated venue is expected to produce on request.

## 4. Possible Root Causes

- N/A -- this is a procedural workflow. Each specific maintenance action has its own workflow (minor-version-upgrade-readiness, parameter-group-change-management, disaster-recovery/cluster-failover-drill, schema-changes/*); this one wraps whichever of them is being executed.

## 5. Investigation Strategy

1. Before the window: confirm the cluster's current activity level, that no long-running transaction or in-flight maintenance operation will be destroyed mid-flight, and that no blocking chain is already in progress.
2. Before the window: confirm the topology is what you think it is (which instance is writer), that every reader is healthy and low-lag, and that no replication slot is silently retaining WAL.
3. Hold an explicit go/no-go on that evidence rather than proceeding by default.
4. After the window: confirm settings, connectivity, topology, and workload health against the pre-window baseline before declaring completion.

## 6. Prerequisites

- pg_monitor role membership for the read-only scripts; an agreed, communicated window; a verified recent backup (disaster-recovery/backup-and-restore-validation); the specific maintenance action's own workflow read in advance.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_pre_window_activity_and_transactions.sql`](scripts/01_pre_window_activity_and_transactions.sql) -- Pre-window snapshot of overall activity and of any transaction long-running enough to be destroyed mid-flight by the maintenance action.
2. [`scripts/02_pre_window_lock_and_blocking_check.sql`](scripts/02_pre_window_lock_and_blocking_check.sql) -- Pre-window check for an existing blocking chain or a DDL lock wait already in progress, either of which means the cluster is unhealthy before the maintenance even starts.
3. [`scripts/03_pre_window_topology_and_replication_check.sql`](scripts/03_pre_window_topology_and_replication_check.sql) -- Pre-window confirmation of which instance is the writer, that every reader is healthy and low-lag, and that no replication slot is silently retaining WAL.
4. [`scripts/04_maintenance_window_checklist.md`](scripts/04_maintenance_window_checklist.md) -- The checklist itself: the ordered pre-window, go/no-go, in-window, and post-window steps that wrap whichever specific maintenance action is being performed.
5. [`scripts/05_post_window_verification.sql`](scripts/05_post_window_verification.sql) -- Post-window verification: settings versus intent, writer identity, connection recovery shape, and transaction age -- run before declaring the window closed.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- On Aurora, most disruptive maintenance ultimately manifests as a reboot or a failover of the writer, and the application-visible behavior is the same in both cases: every connection is reset and the cluster endpoint re-resolves. That means disaster-recovery/cluster-failover-drill is the most useful rehearsal for almost any window in this category, regardless of what is actually being changed.

## 8. Interpretation Guide

- The pre-window scripts are a go/no-go input, not a formality: a transaction that has been open for hours, an index build in progress, or a reader already lagging are each individually sufficient reason to delay a window rather than proceed and discover the consequence mid-change.
- An existing blocking chain before the window means the cluster is already unhealthy; performing disruptive maintenance on top of it makes attribution of whatever happens next nearly impossible.
- Post-window, 'the cluster accepts connections' is not the completion criterion. The criterion is: the expected instance is the writer, settings match intent, connection counts have recovered to a normal shape rather than a reconnect storm, and no new blocking or error pattern has appeared.
- Comparing post-window key settings against the pre-window snapshot is what catches a change that was half-applied (parameter group updated, reboot performed on only some instances) -- see maintenance/parameter-group-change-management.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If a pre-window check fails, delay the window. If a post-window check fails, do not hand the platform back -- treat it as an active incident and use the matching incident workflow.

**Short-term remediation** (hours to days):

- Record the pre-window and post-window script output in the change ticket for every window, so the next window starts from evidence rather than memory.

**Long-term engineering fix** (days to weeks):

- Automate the pre- and post-window script runs into the deployment/maintenance pipeline (see automation/health-checks) so the evidence is collected identically every time, and review overrun windows as a trend to find which class of maintenance consistently takes longer than planned.

## 10. Production Safety

- Every SQL script in this workflow is strictly read-only and safe to run during live trading, including immediately before the window opens.
- This workflow performs no maintenance action itself -- the disruptive step always belongs to the specific workflow being wrapped, and its own safety notes govern.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Any pre-window check fails and there is pressure to proceed anyway -- escalate the go/no-go decision rather than absorbing it.
- The window's planned duration has elapsed and the change is not complete -- escalate and start the rollback path defined by the specific maintenance action's own workflow rather than extending the window indefinitely.

## 12. Related Issues

- [minor-version-upgrade-readiness](../minor-version-upgrade-readiness/README.md)
- [parameter-group-change-management](../parameter-group-change-management/README.md)
- [routine-maintenance-checklist](../routine-maintenance-checklist/README.md)
- [cluster-failover-drill](../../disaster-recovery/cluster-failover-drill/README.md)
- [comprehensive-health-check](../../database-health/comprehensive-health-check/README.md)
