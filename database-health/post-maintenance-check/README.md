# Post-Maintenance Health Check

**Category:** Database Health Checks | **Workflow:** `database-health/post-maintenance-check`

## 1. Problem Description

The verification sweep run immediately after a planned infrastructure operation -- a failover test, an instance class resize, a major engine version upgrade, or an extension version upgrade -- completes. Its purpose is to confirm the cluster came back in the expected topology and configuration, that replication and connections recovered fully, that no vacuum/XID regression was introduced by an interrupted autovacuum, and that query performance did not silently change, before declaring the maintenance window closed.

## 2. Typical Symptoms

- A planned maintenance operation has just completed and its impact has not yet been verified.
- The maintenance operation reported success, but application-side latency or error rate looks different than before the window.
- A major version upgrade or extension upgrade just finished and configuration/extension versions need to be confirmed against expectations.

## 3. Business Impact

- A restart that interrupted an anti-wraparound autovacuum leaves that table's XID age exactly where it was, or worse, immediately after maintenance -- undetected, this compounds with the next maintenance window's own disruption.
- A major version upgrade can silently change planner defaults or a parameter's effective value; undetected, this produces a query plan regression on the ledger or order-book path that looks like a random performance incident days later, disconnected from the maintenance event that actually caused it.
- Declaring a maintenance window closed while reader lag has not fully recovered leaves users seeing stale balances or order history for longer than necessary, with no one aware it is still an open issue.

## 4. Possible Root Causes

- This workflow verifies rather than root-causes: each finding hands off to the dedicated workflow that owns that failure mode.
- A restart interrupting an in-flight anti-wraparound autovacuum, leaving XID age unimproved or elevated.
- A major version upgrade or parameter-group change altering a planner setting, default, or extension version from what was expected.
- A reconnect storm after the restart leaving the connection pool in an unexpected state (some pools not recovering cleanly).
- Slower-than-normal reader catch-up after the writer restart, especially on a cluster with high WAL generation.

## 5. Investigation Strategy

1. Confirm instance topology and uptime reflect the maintenance event as expected (correct instance now the writer, uptime consistent with the restart time).
2. Check Aurora reader lag against the pre-maintenance baseline to confirm full recovery.
3. Check connection headroom and mix to confirm the application fleet reconnected cleanly.
4. Check for any blocked sessions or lock contention immediately after the restart.
5. Check vacuum and transaction ID age to confirm no regression from an interrupted autovacuum.
6. Verify configuration settings and extension versions against the pre-maintenance baseline.
7. Compare query performance against the pre-maintenance baseline.

## 6. Prerequisites

- Role membership in pg_monitor (or pg_read_all_stats).
- The pre-maintenance baseline output from pre-maintenance-check, without which several of these comparisons are guesswork.
- The maintenance change record describing exactly what was expected to change (settings, extension versions, instance class).
- pg_stat_statements, ideally not reset between the baseline capture and this run (note that a major version upgrade or extension upgrade may reset it regardless).

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_instance_topology_and_uptime.sql`](scripts/01_instance_topology_and_uptime.sql) -- Confirms writer/reader topology and instance uptime reflect the completed maintenance operation.
2. [`scripts/02_replication_lag_after_maintenance.sql`](scripts/02_replication_lag_after_maintenance.sql) -- Re-checks Aurora reader lag for direct comparison against the pre-maintenance baseline.
3. [`scripts/03_connection_recovery_check.sql`](scripts/03_connection_recovery_check.sql) -- Confirms the application fleet reconnected cleanly after the restart.
4. [`scripts/04_blocking_and_lock_check.sql`](scripts/04_blocking_and_lock_check.sql) -- Checks for blocked sessions immediately after the restart.
5. [`scripts/05_vacuum_and_xid_status.sql`](scripts/05_vacuum_and_xid_status.sql) -- Checks autovacuum activity and transaction ID age for a regression caused by an interrupted vacuum.
6. [`scripts/06_settings_and_extension_verification.sql`](scripts/06_settings_and_extension_verification.sql) -- Re-captures configuration settings and extension inventory for comparison against the pre-maintenance baseline.
7. [`scripts/07_query_performance_vs_baseline.sql`](scripts/07_query_performance_vs_baseline.sql) -- Re-captures top statements by total time for direct comparison against the pre-maintenance baseline.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- A restart (whether from a resize, major version upgrade, or parameter-group reboot) resets pg_stat_statements, pg_stat_database, and pg_stat_checkpointer on the affected instance -- a 'change' in these counters immediately after maintenance is expected, not a finding, unless it persists well past a fresh accumulation window.
- After a major version upgrade, run ANALYZE-freshness verification (statistics_freshness in post-deployment-check) as well: some upgrade paths recommend or require a statistics refresh, and stale statistics immediately post-upgrade are a common source of an apparent plan regression that is actually just an unrefreshed planner.
- Aurora reader instances resume redo application from the shared storage layer after a restart; expect a brief lag spike immediately after recovery even when nothing is wrong, and judge convergence over a few minutes rather than expecting instant zero lag.

## 8. Interpretation Guide

- Compare every finding against the specific pre-maintenance baseline captured for this window, not against a generic 'healthy' number -- the question is whether this operation changed anything, not whether the cluster looks healthy in the abstract.
- Some cumulative counters (pg_stat_statements, pg_stat_database) reset on a restart by design -- a 'regression' that is actually just a fresh counting window since the restart is not a finding, it is expected. Check stats_reset before concluding anything from a counter comparison.
- A settings or extension-version difference from the baseline that was not part of the planned change is the most actionable finding this workflow can produce -- it usually means the operation had a side effect nobody planned for.
- Give reader lag a few minutes to catch up after a restart before treating elevated lag as a finding; the concerning case is lag that is not converging back toward baseline after a reasonable interval, not a brief spike immediately after recovery.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If a settings or extension-version drift is found that was not part of the planned change, correct it in the parameter group and document why it happened before closing the maintenance ticket.
- If reader lag is not converging after a reasonable interval, escalate to replication-and-ha/reader-lag-investigation rather than waiting indefinitely.
- If XID age did not improve as expected because an anti-wraparound autovacuum was interrupted, confirm autovacuum has resumed on the affected table and is progressing.

**Short-term remediation** (hours to days):

- File the specific regressed statement (if any) with its baseline and post-maintenance numbers to the team that requested the maintenance.
- Update the maintenance runbook with any unexpected side effect found, so the next occurrence of this operation anticipates it.

**Long-term engineering fix** (days to weeks):

- Automate the baseline-versus-post comparison for recurring maintenance operations (e.g. scheduled failover drills) so it runs and reports automatically rather than depending on someone remembering to check.
- Feed configuration and extension-version drift findings back into infrastructure-as-code so the parameter group definition matches what is actually running.

## 10. Production Safety

- Every script here is read-only; none of them runs DDL, VACUUM, or any write.
- Safe to run immediately after maintenance completes, including during the tail end of an announced maintenance window.
- Remediating a finding (parameter-group correction, index rebuild, vacuum) is out of scope for these scripts and is handled by the referenced dedicated runbooks.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Reader lag has not started converging back toward the pre-maintenance baseline within the expected recovery interval.
- A configuration setting or extension version differs from the baseline in a way that was not part of the planned change.
- Any statement on the order-placement, balance-check, withdrawal, or settlement path is measurably slower than its pre-maintenance baseline.
- XID age on any table did not improve as expected after maintenance that was supposed to include a vacuum pass, or is now closer to the wraparound threshold than before the window opened.

## 12. Related Issues

- [pre-maintenance-check](../pre-maintenance-check/README.md)
- [comprehensive-health-check](../comprehensive-health-check/README.md)
- [failover-investigation](../../replication-and-ha/failover-investigation/README.md)
- [reader-lag-investigation](../../replication-and-ha/reader-lag-investigation/README.md)
- [cluster-failover-drill](../../disaster-recovery/cluster-failover-drill/README.md)
- [xid-wraparound-risk](../../transactions-and-xid/xid-wraparound-risk/README.md)
