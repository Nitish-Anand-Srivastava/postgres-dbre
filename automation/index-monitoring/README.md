# Scheduled Index Health Monitoring

**Category:** Automation | **Workflow:** `automation/index-monitoring`

## 1. Problem Description

The automated, scheduled counterpart to tables-and-indexes/unused-indexes and tables-and-indexes/invalid-indexes -- and to storage-and-capacity/index-growth's usage-context review. Index accretion (indexes added one at a time to fix individual slow queries, never reviewed as a set) is a slow, easy-to-miss trend; this workflow documents capturing unused, invalid, and usage/size context on a recurring schedule so the trend is visible before an ad-hoc cleanup project is the only option left.

## 2. Typical Symptoms

- tables-and-indexes/unused-indexes or tables-and-indexes/invalid-indexes has been run manually more than once with recurring findings, and the team wants it scheduled instead.
- storage-and-capacity/index-growth found that index accretion is an ongoing, not one-off, problem.
- An index cleanup project keeps needing to be redone from scratch because there is no standing record of what was already reviewed.

## 3. Business Impact

- Every unreviewed unused or invalid index is recurring, compounding cost -- storage, write amplification, and vacuum time -- that a one-off cleanup only resets rather than prevents from recurring.
- A recurring, recorded index-health check turns index hygiene into a standing, low-effort operational practice instead of an occasional large project.

## 4. Possible Root Causes

- N/A -- this is a scheduling/automation workflow. See tables-and-indexes/unused-indexes, tables-and-indexes/invalid-indexes, and storage-and-capacity/index-growth for root-cause analysis and remediation of any specific finding.

## 5. Investigation Strategy

1. Capture unused-index, invalid-index, and index usage/size context snapshots as the baseline.
2. Schedule these captures to run and be recorded on a recurring (typically weekly or monthly) cadence.
3. Review the recorded history periodically, rather than only reacting to a single point-in-time run.

## 6. Prerequisites

- `pg_monitor` role membership (or `pg_read_all_stats`) for the read-only scripts in this workflow.
- `pg_cron` must already be installed in this database. It must first be added to `shared_preload_libraries` on the Aurora DB cluster parameter group (requires a reboot to take effect), and then `CREATE EXTENSION pg_cron;` must be run once by an administrator in a change-managed session. This script never creates or schedules anything -- it only detects whether pg_cron is already installed, and prints an instructional notice instead of failing if it is not. Only required if scheduling via pg_cron; the external-scheduler alternative in the runbook has no such dependency.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_unused_indexes_snapshot.sql`](scripts/01_unused_indexes_snapshot.sql) -- Unused-index candidate snapshot, intended to be captured on every scheduled run.
2. [`scripts/02_invalid_indexes_snapshot.sql`](scripts/02_invalid_indexes_snapshot.sql) -- INVALID-index snapshot, intended to be captured on every scheduled run so a failed concurrent build is caught promptly rather than discovered incidentally.
3. [`scripts/03_index_usage_and_size_snapshot.sql`](scripts/03_index_usage_and_size_snapshot.sql) -- Index size, scan-count, and last-used snapshot, intended to be captured on every scheduled run to track index-growth and usage trends over time.
4. [`scripts/04_duplicate_indexes_snapshot.sql`](scripts/04_duplicate_indexes_snapshot.sql) -- Redundant/duplicate index snapshot, intended to be captured on every scheduled run so indexes added by successive migrations that duplicate an existing one are caught early.
5. [`scripts/05_scheduling_runbook.md`](scripts/05_scheduling_runbook.md) -- Documents how to run the index-health snapshot scripts on a recurring schedule via pg_cron or an external scheduler.

## 8. Interpretation Guide

- A single scheduled run's findings should be treated exactly as tables-and-indexes/unused-indexes and tables-and-indexes/invalid-indexes already document -- idx_scan resets on restart/failover, so never act on one run's zero-scan result alone; confirm persistence across multiple scheduled runs spanning at least one full business cycle first.
- An index appearing as an unused-index candidate across many consecutive scheduled runs, with no restart/failover in between, is much stronger evidence than a single manual check happening to catch it once.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- N/A -- this workflow is scheduling/automation. Any specific finding is remediated through tables-and-indexes/unused-indexes, tables-and-indexes/invalid-indexes, or tables-and-indexes/duplicate-indexes.

**Short-term remediation** (hours to days):

- Deploy the scheduled captures in this workflow's runbook if they are not already running.

**Long-term engineering fix** (days to weeks):

- Review the recorded index-health history on a standing cadence (e.g. quarterly) as an input to a routine index cleanup pass, rather than only after a storage or performance problem prompts an ad-hoc review.

## 10. Production Safety

- Every `.sql` script in this workflow is strictly read-only, identical in safety profile to the tables-and-indexes/storage-and-capacity scripts it schedules.
- The scheduling runbook documents a pg_cron job or external scheduler invocation -- markdown, never auto-executed by this repository. No index is ever dropped or rebuilt by anything in this workflow.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- A scheduled run finds a newly-INVALID index on a core trading-path table -- treat this the same as tables-and-indexes/invalid-indexes recommends, since it indicates a recent failed concurrent build that may warrant investigation in its own right.

## 12. Related Issues

- [growth-monitoring](../growth-monitoring/README.md)
- [unused-indexes](../../tables-and-indexes/unused-indexes/README.md)
- [invalid-indexes](../../tables-and-indexes/invalid-indexes/README.md)
- [index-growth](../../storage-and-capacity/index-growth/README.md)
