# 05_routine_maintenance_checklist

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `05_routine_maintenance_checklist.md` |
| Purpose | The checklist itself: the ordered list of checks to run each cycle, what to do with each finding, and the cadence this workflow is intended to run on. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only (the query reads/writes state that only exists or is meaningful on the writer) |
| Safety | DOCUMENTATION -- no SQL executed by this file itself |
| Expected impact | None from this file directly; hand-off workflows carry their own impact. |
| Required privileges | N/A for this file itself; see the hand-off workflow for its own required privileges. |
| Prerequisites | Full read-only investigation for this workflow completed; maintenance window and second engineer approval obtained. |
| Execution order | Step 05 of workflow `maintenance/routine-maintenance-checklist` |
| Related scripts | 01_dead_tuples_and_autovacuum_activity.sql, 02_index_bloat_and_usage.sql, 03_statistics_freshness.sql, 04_extension_and_key_settings_inventory.sql |

## How to interpret / use this runbook

Follow the checklist in order once per scheduled cycle; the value of this workflow comes from consistent cadence and consistent hand-off, not from any single run in isolation.

---

## Cadence

Run this checklist on a fixed cadence (weekly is a reasonable starting point for a high-throughput exchange platform; monthly at minimum) regardless of whether any incident has occurred -- its value is in catching a slow trend before it becomes one.

## Checklist

1. Run `01_dead_tuples_and_autovacuum_activity.sql`. Hand off any table with a worsening trend to `vacuum-and-autovacuum/dead-tuples` or `vacuum-and-autovacuum/autovacuum-not-keeping-up`.
2. Run `02_index_bloat_and_usage.sql`. Hand off unused indexes to `tables-and-indexes/unused-indexes`; hand off bloated-but-used indexes to `reindex-strategy` in this category.
3. Run `03_statistics_freshness.sql`. Hand off stale tables to `vacuum-and-autovacuum/analyze-statistics`.
4. Run `04_extension_and_key_settings_inventory.sql`. Compare against the previous run's saved output and the documented baseline; hand off any extension needing an upgrade to `extension-upgrade-planning` in this category.
5. Confirm `disaster-recovery/backup-and-restore-validation` has been run within its own required cadence -- this checklist does not re-run that workflow's steps itself, it only confirms the standing evidence exists.
6. File or update a single tracking ticket per cycle recording the date, findings, and any hand-offs created, so trends across cycles are reviewable later.

## What this checklist is not

This is a review-and-triage checklist, not a remediation workflow -- every finding here should be handed off to the specific dedicated workflow named above (which has its own full investigation, interpretation, and remediation guidance) rather than acted on directly from this checklist.
