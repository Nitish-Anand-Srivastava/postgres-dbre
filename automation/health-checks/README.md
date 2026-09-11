# Scheduling Routine Health Checks

**Category:** Automation | **Workflow:** `automation/health-checks`

## 1. Problem Description

Documents how to run the database-health/ workflows (daily-health-check, comprehensive-health-check, capacity-health-check, and the pre/post-deployment and pre/post-maintenance checks) on a recurring, unattended schedule instead of manually and inconsistently. Two scheduling mechanisms are covered: `pg_cron` running inside the database when it is enabled on the cluster parameter group, and an external scheduler (an AWS Lambda function on an EventBridge/CloudWatch Events cron rule, invoking the database via the RDS Data API or a network path to the writer) when it is not. This workflow itself performs no scheduling -- it is diagnostic (does pg_cron already have jobs registered) and documentary (how to add more), never an auto-executing setup step.

## 2. Typical Symptoms

- Health checks are only ever run manually, inconsistently, and usually only after something has already gone wrong.
- A recent incident review found that a health-check finding (rising XID age, a growing unused index, a capacity threshold) had been true for weeks before anyone happened to look.
- A capacity or database-health workflow's remediation-long-term section recommends 'run this on a schedule' with no existing schedule in place.

## 3. Business Impact

- An unscheduled health check is only as good as someone remembering to run it -- on a 24/7 exchange platform, the gap between 'this would have been caught' and 'this was actually caught' is where slow-burning incidents (XID age, storage growth, capacity exhaustion) turn into outages.
- Consistent scheduled health checks produce a comparable historical record (did this get worse since last week), which a one-off manual run never can.

## 4. Possible Root Causes

- N/A -- this is a scheduling/automation workflow, not an incident investigation.

## 5. Investigation Strategy

1. Check whether `pg_cron` is already installed and, if so, what jobs (if any) are already registered.
2. If `pg_cron` has registered jobs, review their recent run history for failures before assuming the schedule is working.
3. If `pg_cron` is not installed or not appropriate for this cluster, use the external-scheduler pattern documented in this workflow's runbook instead.

## 6. Prerequisites

- `pg_monitor` role membership (or `pg_read_all_stats`) for the read-only checks in this workflow.
- `pg_cron` must already be installed in this database. It must first be added to `shared_preload_libraries` on the Aurora DB cluster parameter group (requires a reboot to take effect), and then `CREATE EXTENSION pg_cron;` must be run once by an administrator in a change-managed session. This script never creates or schedules anything -- it only detects whether pg_cron is already installed, and prints an instructional notice instead of failing if it is not. Only required for scripts 01-02; the external-scheduler path in script 03 has no such dependency.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_pg_cron_extension_and_jobs.sql`](scripts/01_pg_cron_extension_and_jobs.sql) -- Checks whether pg_cron is installed in this database and, if so, lists every job currently registered.
2. [`scripts/02_pg_cron_recent_job_run_history.sql`](scripts/02_pg_cron_recent_job_run_history.sql) -- Checks whether pg_cron is installed and, if so, reports the most recent run outcome for every registered job.
3. [`scripts/03_quick_health_signal.sql`](scripts/03_quick_health_signal.sql) -- The single lightweight, read-only health signal a scheduled job should capture on every run: instance role, connection headroom, and transaction ID age.
4. [`scripts/04_scheduling_runbook.md`](scripts/04_scheduling_runbook.md) -- Documents how to schedule the database-health/ workflows on a recurring basis, via pg_cron where it is enabled or an external scheduler where it is not.

## 8. Interpretation Guide

- A database with no `pg_cron` jobs registered and no external scheduler in place is not automatically broken -- it simply means every database-health workflow is currently run manually. Treat that as the starting point to fix, not as an error.
- A registered `pg_cron` job with a recent run history full of failures is worse than no job at all -- it creates false confidence that a check is happening when it is not. Always review script 02's output before trusting that a schedule is working.
- Prefer `pg_cron` for checks that only need to run inside the database and whose output can be logged to a table pg_cron itself can write to; prefer the external-scheduler pattern when the check's output needs to reach an external alerting system (PagerDuty, Slack, CloudWatch alarms) directly.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- N/A -- this workflow is diagnostic and documentary; no action is taken automatically.

**Short-term remediation** (hours to days):

- Schedule the highest-value health check (typically daily-health-check or capacity-health-check) first, following the runbook in this workflow, before attempting to schedule every workflow in the repository at once.

**Long-term engineering fix** (days to weeks):

- Schedule every relevant database-health/ workflow on a documented cadence (daily for daily-health-check, weekly or monthly for the heavier comprehensive-health-check and capacity-health-check).
- Route health-check findings into the same alerting/ticketing system used for other operational alerts, so a health-check finding gets the same visibility as a paging incident.

## 10. Production Safety

- Every `.sql` script in this workflow is strictly read-only.
- The runbook in script 03 documents scheduling steps for the operator to review and apply deliberately -- it is markdown, not an executable script, and is never auto-run by anything in this repository.
- Adding `pg_cron` to `shared_preload_libraries` requires an Aurora instance reboot -- always schedule that change through the same change-management process as any other cluster parameter group change.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- A scheduled health check has been silently failing (per script 02) for long enough that its findings could not have been acted on -- treat any finding from the next successful run with extra scrutiny and review why the failures went unnoticed.

## 12. Related Issues

- [growth-monitoring](../growth-monitoring/README.md)
- [capacity-monitoring](../capacity-monitoring/README.md)
- [daily-health-check](../../database-health/daily-health-check/README.md)
- [comprehensive-health-check](../../database-health/comprehensive-health-check/README.md)
