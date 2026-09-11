# Scheduled Transaction ID Age Monitoring

**Category:** Automation | **Workflow:** `automation/xid-monitoring`

## 1. Problem Description

The automated, scheduled counterpart to transactions-and-xid/transaction-age's manual database- and table-level XID age snapshots. Transaction ID wraparound risk is exactly the kind of slow-burning problem that a manual, occasionally-remembered check will eventually miss -- this workflow documents running the same read-only age checks on a recurring schedule with alert thresholds set well below the emergency failsafe, so a climbing trend is caught weeks before it becomes urgent.

## 2. Typical Symptoms

- transactions-and-xid/transaction-age has been run manually more than once and the team wants it scheduled instead.
- A prior XID wraparound risk incident's retrospective recommended automated monitoring as a long-term fix.
- No one can currently answer 'is our XID age trend improving or worsening' without running a manual check right now.

## 3. Business Impact

- Transaction ID wraparound, if it is ever allowed to reach the enforced limit, forces PostgreSQL to refuse new writes entirely -- a full outage. Scheduled monitoring with a conservative alert threshold is what keeps this a routine autovacuum-tuning conversation instead of an emergency.
- A climbing XID age trend is actionable weeks in advance if caught early (tune autovacuum, address a holding-back long-running transaction) but requires an emergency, high-risk manual VACUUM (FREEZE) if caught only at the failsafe threshold.

## 4. Possible Root Causes

- N/A -- this is a scheduling/automation workflow. See transactions-and-xid/xid-wraparound-risk for root-cause analysis once a scheduled check reports an elevated age.

## 5. Investigation Strategy

1. Confirm the current database- and table-level XID age as the baseline (the same checks as transactions-and-xid/transaction-age).
2. Schedule these checks to run and be recorded on a recurring cadence, per this workflow's runbook.
3. Set an alert threshold well below the emergency failsafe (commonly 40-50% of autovacuum_freeze_max_age) so there is real lead time to act.

## 6. Prerequisites

- `pg_monitor` role membership (or `pg_read_all_stats`) for the read-only age-check scripts.
- `pg_cron` must already be installed in this database. It must first be added to `shared_preload_libraries` on the Aurora DB cluster parameter group (requires a reboot to take effect), and then `CREATE EXTENSION pg_cron;` must be run once by an administrator in a change-managed session. This script never creates or schedules anything -- it only detects whether pg_cron is already installed, and prints an instructional notice instead of failing if it is not. Only required if scheduling via pg_cron; the external-scheduler alternative in the runbook has no such dependency.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_database_age_snapshot.sql`](scripts/01_database_age_snapshot.sql) -- Database-level XID age snapshot, intended to be captured on every scheduled run.
2. [`scripts/02_table_age_snapshot.sql`](scripts/02_table_age_snapshot.sql) -- Table-level XID age snapshot (top N oldest tables), intended to be captured on every scheduled run.
3. [`scripts/03_scheduling_runbook.md`](scripts/03_scheduling_runbook.md) -- Documents how to run the XID age snapshot scripts on a recurring schedule, with a recommended alert threshold, via pg_cron or an external scheduler.

## 8. Interpretation Guide

- Track pct_of_freeze_max_age as a trend over successive scheduled runs, not just its current value -- a slowly climbing trend is actionable long before any single snapshot looks alarming, and a scheduled history is what makes the trend visible at all.
- Any scheduled run reporting age above roughly 75% of autovacuum_freeze_max_age should escalate immediately to transactions-and-xid/xid-wraparound-risk rather than waiting for the next scheduled run.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- N/A -- this workflow is scheduling/automation. Any single elevated finding should be escalated directly to transactions-and-xid/transaction-age or transactions-and-xid/xid-wraparound-risk.

**Short-term remediation** (hours to days):

- Deploy the scheduled checks in this workflow's runbook if they are not already running, using a conservative alert threshold from day one.

**Long-term engineering fix** (days to weeks):

- Feed the scheduled history into the same dashboard/alerting stack used for other operational monitoring, so a climbing XID age trend gets the same visibility as any other capacity or health signal.

## 10. Production Safety

- The read-only age-check scripts in this workflow are identical in safety profile to transactions-and-xid/transaction-age's scripts -- strictly read-only, safe at any time.
- The scheduling runbook documents a pg_cron job or external scheduler invocation -- markdown, never auto-executed by this repository.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- A scheduled run reports database or table age above 75% of autovacuum_freeze_max_age -- escalate immediately to transactions-and-xid/xid-wraparound-risk regardless of when the next scheduled run would otherwise occur.

## 12. Related Issues

- [growth-monitoring](../growth-monitoring/README.md)
- [transaction-age](../../transactions-and-xid/transaction-age/README.md)
- [xid-wraparound-risk](../../transactions-and-xid/xid-wraparound-risk/README.md)
