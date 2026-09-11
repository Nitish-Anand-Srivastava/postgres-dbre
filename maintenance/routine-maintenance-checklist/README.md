# Routine Maintenance Checklist

**Category:** Maintenance | **Workflow:** `maintenance/routine-maintenance-checklist`

## 1. Problem Description

A recurring, standing checklist covering vacuum/autovacuum health, index bloat, planner statistics freshness, extension/settings drift, and a pointer to backup verification -- the standard set of checks a DBA runs on a regular cadence (weekly/monthly) rather than only reactively during an incident.

## 2. Typical Symptoms

- No active symptom -- this is a scheduled, proactive workflow, not an incident-response one.
- Run ahead of a compliance/operational review to produce evidence the cluster is being actively maintained.

## 3. Business Impact

- Most of the incidents covered elsewhere in this repository (autovacuum falling behind, bloat accumulating unnoticed, stale statistics causing plan regressions) are cheaper to prevent via a regular checklist than to diagnose after they have already caused a customer-visible incident.

## 4. Possible Root Causes

- N/A -- this is a preventive/monitoring workflow, not a root-cause investigation for a single symptom.

## 5. Investigation Strategy

1. Check dead-tuple accumulation and autovacuum activity across the cluster's tables.
2. Check index bloat/usage for obviously bloated or unused indexes.
3. Check planner statistics freshness.
4. Check installed extension versions and key settings for unexpected drift from the documented baseline.
5. Confirm backup/restore verification (disaster-recovery/backup-and-restore-validation) has run within its own cadence.

## 6. Prerequisites

- pg_monitor role membership.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_dead_tuples_and_autovacuum_activity.sql`](scripts/01_dead_tuples_and_autovacuum_activity.sql) -- Ranks tables by dead-tuple volume and shows currently active autovacuum workers, the first stop for the vacuum-health portion of the checklist.
2. [`scripts/02_index_bloat_and_usage.sql`](scripts/02_index_bloat_and_usage.sql) -- Surfaces index size, scan counts, and last-used timestamps to catch both bloated and simply-unused indexes as part of the routine review.
3. [`scripts/03_statistics_freshness.sql`](scripts/03_statistics_freshness.sql) -- Checks how stale planner statistics are across tables, since this checklist is often the first place staleness is noticed before it causes a plan regression.
4. [`scripts/04_extension_and_key_settings_inventory.sql`](scripts/04_extension_and_key_settings_inventory.sql) -- Snapshots installed extension versions and the settings most likely to drift or matter operationally, to catch unexpected configuration/version drift between checklist runs.
5. [`scripts/05_routine_maintenance_checklist.md`](scripts/05_routine_maintenance_checklist.md) -- The checklist itself: the ordered list of checks to run each cycle, what to do with each finding, and the cadence this workflow is intended to run on.

## 8. Interpretation Guide

- Treat this checklist as a trend-line exercise, not a single-snapshot pass/fail -- a slowly worsening dead-tuple count or a statistics-freshness gap that widens run over run is the actual signal, even when any single run looks unremarkable in isolation.
- A finding here that matches an existing dedicated workflow (e.g. dead tuples piling up) should be handed off to that workflow (vacuum-and-autovacuum/dead-tuples) for the full investigation rather than remediated ad hoc from this checklist.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- N/A -- pivot to the specific matching workflow (vacuum-and-autovacuum/*, tables-and-indexes/index-bloat, query-optimization/stale-statistics) for any finding that needs immediate action.

**Short-term remediation** (hours to days):

- Schedule follow-up on any finding that is trending worse run over run, even if not yet at an actionable threshold.

**Long-term engineering fix** (days to weeks):

- Automate this checklist's read-only steps into a scheduled job (see automation/health-checks) so the checklist itself does not depend on someone remembering to run it manually.

## 10. Production Safety

- Every SQL script in this checklist is read-only.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- A trend line across multiple checklist runs shows a metric worsening toward a known danger threshold (e.g. dead-tuple ratio, transaction ID age) with no corrective action yet taken -- escalate before it becomes an active incident.

## 12. Related Issues

- [dead-tuples](../../vacuum-and-autovacuum/dead-tuples/README.md)
- [autovacuum-not-keeping-up](../../vacuum-and-autovacuum/autovacuum-not-keeping-up/README.md)
- [daily-health-check](../../database-health/daily-health-check/README.md)
- [backup-and-restore-validation](../../disaster-recovery/backup-and-restore-validation/README.md)
