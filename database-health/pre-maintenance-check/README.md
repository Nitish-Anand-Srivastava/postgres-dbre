# Pre-Maintenance Health Check

**Category:** Database Health Checks | **Workflow:** `database-health/pre-maintenance-check`

## 1. Problem Description

The go/no-go baseline captured immediately before a planned infrastructure operation -- a failover test, an instance class resize, a major engine version upgrade, or an extension version upgrade -- rather than an application deployment. It answers 'is it safe to start this operation now, and what does healthy look like so we can tell whether the operation itself introduced a regression?' A resize or major-version upgrade forces a writer restart (and therefore a failover in a multi-instance cluster); starting one while a transaction is open, a vacuum is mid-flight, or a reader is already lagging turns a planned few minutes of downtime into an extended incident.

## 2. Typical Symptoms

- No active symptom -- this is a scheduled gate run in the minutes before a maintenance window opens (failover drill, instance resize, major version upgrade, extension upgrade, parameter-group change requiring a reboot).
- Run again after an aborted maintenance attempt, before retrying.
- Used as the evidence baseline attached to the maintenance ticket so post-maintenance-check has something concrete to compare against.

## 3. Business Impact

- A major version upgrade or instance resize forces the writer to restart; if that restart lands while a long transaction or an anti-wraparound autovacuum is in flight, recovery after the restart takes measurably longer and the trading halt extends well past the announced window.
- Starting maintenance while a reader is already lagging compounds the outage: readers briefly fall further behind during the writer restart, and an already-elevated baseline means the recovery tail is longer and read-your-own-write violations last longer for users.
- Without a captured pre-maintenance baseline, the team cannot distinguish 'this is a known side effect of the maintenance operation' from 'this is a new regression the operation introduced', which turns every maintenance window into a debugging exercise.

## 4. Possible Root Causes

- Not a failure workflow -- these are the pre-existing conditions that make starting maintenance right now unsafe, or that need to be recorded before it starts.
- A long-running transaction or prepared transaction that the restart will forcibly abort, leaving its owning service to handle an unexpected disconnection instead of a clean commit/rollback.
- An in-flight autovacuum (especially an anti-wraparound vacuum) that a restart interrupts, forcing it to restart its scan from the beginning afterward.
- Reader lag or connection headroom already outside normal bounds before the operation even begins, which the maintenance operation itself will make temporarily worse.

## 5. Investigation Strategy

1. Confirm cluster topology and instance uptime, so it is clear which instance is the current writer and how long it has been running.
2. Check connection headroom and the per-application connection mix, since the operation will force a reconnect storm.
3. Check for long-running transactions and prepared transactions that the restart would forcibly abort.
4. Record the current Aurora reader lag as the pre-maintenance baseline.
5. Check whether autovacuum (especially anti-wraparound autovacuum) is currently running on any table.
6. Snapshot key configuration settings and the installed extension inventory, so post-maintenance-check can confirm nothing drifted unexpectedly.
7. Capture a query-performance baseline for the post-maintenance comparison.

## 6. Prerequisites

- Role membership in pg_monitor (or pg_read_all_stats).
- The maintenance change record (what operation, on which instance(s), and the announced window) so findings can be read in that context.
- An agreed abort/reschedule threshold for each check, decided before the window opens.
- pg_stat_statements for the baseline capture step (optional; the script degrades gracefully with a notice if absent).

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_instance_topology_and_uptime.sql`](scripts/01_instance_topology_and_uptime.sql) -- Confirms current writer/reader topology and instance uptime before starting the maintenance operation.
2. [`scripts/02_connection_headroom_and_mix.sql`](scripts/02_connection_headroom_and_mix.sql) -- Checks connection headroom and per-application connection mix before the reconnect storm a restart causes.
3. [`scripts/03_open_transactions_and_prepared.sql`](scripts/03_open_transactions_and_prepared.sql) -- Identifies long-running transactions and prepared transactions the restart would forcibly abort.
4. [`scripts/04_replication_lag_baseline.sql`](scripts/04_replication_lag_baseline.sql) -- Records the current Aurora reader lag as the pre-maintenance baseline.
5. [`scripts/05_vacuum_and_xid_status.sql`](scripts/05_vacuum_and_xid_status.sql) -- Checks for in-flight autovacuum (including anti-wraparound autovacuum) and current transaction ID age.
6. [`scripts/06_settings_and_extension_baseline.sql`](scripts/06_settings_and_extension_baseline.sql) -- Captures the current configuration settings and installed extension inventory as a pre-maintenance baseline.
7. [`scripts/07_query_performance_baseline.sql`](scripts/07_query_performance_baseline.sql) -- Captures the pre-maintenance query performance baseline for later comparison.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Aurora applies most parameter-group changes, and every engine major-version upgrade, only via a reboot -- a reboot of the writer is a failover in a multi-instance cluster, so treat any such maintenance as a failover event and run replication-and-ha/failover-readiness alongside this check.
- An in-progress anti-wraparound autovacuum does not block a requested reboot/failover from proceeding, but the restart discards its progress; the vacuum restarts from scratch afterward, so a table that was close to finishing will still show high XID age immediately post-maintenance.
- Aurora minor version upgrades can sometimes apply without a reboot depending on the specific version jump; confirm the specific upgrade path's restart behavior in the AWS documentation for the target engine version before assuming zero downtime.

## 8. Interpretation Guide

- Treat this as a pre-agreed checklist with veto conditions, the same discipline as pre-deployment-check, but the trigger here is an infrastructure operation rather than an application release.
- A long transaction or an in-flight anti-wraparound autovacuum is not merely inconvenient here -- the restart will abort or interrupt it outright, so the finding is 'this work will be lost/interrupted', not just 'this might block something'.
- Reader lag already above baseline before the operation starts is a strong signal to delay: the operation will add to it, not just coexist with it.
- The settings/extension snapshot and query-performance baseline are not pass/fail checks -- their only purpose is to make post-maintenance-check's comparison meaningful, so capture them even when every other check is green.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Postpone the maintenance window if any veto condition is present -- an extra day's delay is far cheaper than an extended trading halt caused by starting mid-transaction.
- If a long transaction or prepared transaction is the only blocker, have its owning team resolve it and re-run this check before proceeding.
- If reader lag is already elevated, wait for it to return to baseline before starting an operation that will add to it.

**Short-term remediation** (hours to days):

- Reschedule recurring maintenance windows away from the times this check repeatedly finds contention (e.g. batch/reconciliation job overlap).
- Coordinate with the owning teams of any long-lived transaction or job in advance of the next maintenance window rather than discovering it at execution time.

**Long-term engineering fix** (days to weeks):

- Automate this check as a required, blocking pre-check in the maintenance runbook/automation tooling so an unsafe window cannot be started manually.
- Track pre-maintenance baselines over time to see whether reader lag, connection headroom, or vacuum debt are trending toward being a recurring blocker.

## 10. Production Safety

- Every script in this workflow is strictly read-only and safe to run at any time, including immediately before an active maintenance window.
- This check never changes anything: it produces a go/no-go decision and a baseline, nothing more.
- Run it against the writer for transaction/connection/vacuum state; run the replication check from any instance since aurora_replica_status() is cluster-wide.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Any transaction open longer than a few minutes, or any prepared transaction at all, with no owner reachable before the window opens.
- An anti-wraparound autovacuum currently running on a large table -- interrupting it via restart means it restarts its scan from the beginning afterward.
- Reader lag already above the application's normal tolerance, or a failover in the last few minutes -- let the cluster stabilize first.
- Connection utilization above 80%, leaving no headroom for the reconnect storm the operation will cause.

## 12. Related Issues

- [post-maintenance-check](../post-maintenance-check/README.md)
- [pre-deployment-check](../pre-deployment-check/README.md)
- [comprehensive-health-check](../comprehensive-health-check/README.md)
- [failover-readiness](../../replication-and-ha/failover-readiness/README.md)
- [cluster-failover-drill](../../disaster-recovery/cluster-failover-drill/README.md)
- [vacuum-progress](../../vacuum-and-autovacuum/vacuum-progress/README.md)
- [long-running-transactions](../../concurrency-and-locking/long-running-transactions/README.md)
