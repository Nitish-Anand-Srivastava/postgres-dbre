# ANALYZE and Planner Statistics

**Category:** Vacuum and Autovacuum | **Workflow:** `vacuum-and-autovacuum/analyze-statistics`

## 1. Problem Description

Investigates whether planner statistics are fresh and representative, distinct from vacuum's tuple-cleanup role -- ANALYZE (whether run manually, via autoanalyze, or as part of autovacuum) is what keeps the query planner's row/selectivity estimates accurate.

## 2. Typical Symptoms

- Query plans that do not match expected row-count estimates.
- n_mod_since_analyze high relative to table size.
- last_analyze/last_autoanalyze significantly stale relative to the table's write rate.

## 3. Business Impact

- Stale statistics are one of the most common root causes of sudden query-plan regressions on an otherwise-unchanged query.

## 4. Possible Root Causes

- autovacuum_analyze_scale_factor too high in absolute terms for a very large table.
- A large bulk load/backfill completed without a follow-up manual ANALYZE.
- autoanalyze disabled or starved similarly to autovacuum (shares the same worker pool and cost settings).

## 5. Investigation Strategy

1. Check statistics freshness (modifications since last analyze) across tables.
2. For any table suspected of a plan regression, manually ANALYZE it and compare plans before/after.
3. Consider a higher statistics target for specific skewed columns.

## 6. Prerequisites

- pg_monitor role membership; table-owner privilege to run ANALYZE manually.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_statistics_freshness.sql`](scripts/01_statistics_freshness.sql) -- Checks statistics freshness (modifications since last analyze) across all tables.

## 8. Interpretation Guide

- Distinguish ANALYZE (statistics only, all data types, fast, no data rewrite) from VACUUM ANALYZE (does both). Running ANALYZE alone is comparatively cheap and safe to run more frequently than a full VACUUM pass if statistics freshness -- not bloat -- is the specific concern.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- `ANALYZE schema.table_name;` (targeted, not database-wide) for any table with clearly stale statistics implicated in a current performance issue.

**Short-term remediation** (hours to days):

- Lower autovacuum_analyze_scale_factor for large tables so autoanalyze triggers more frequently in absolute row-count terms.
- Increase the statistics target (`ALTER TABLE ... ALTER COLUMN ... SET STATISTICS n;`) for specific columns with skewed distributions that the planner is misjudging.

**Long-term engineering fix** (days to weeks):

- Adopt a habit of running a manual, targeted ANALYZE immediately after any large bulk load/backfill/migration as a standard runbook step.

## 10. Production Safety

- ANALYZE takes only a brief, low-impact lock (does not block reads/writes) and never rewrites table data -- safe to run on production at any time.
- Never run a blind, database-wide `ANALYZE;` as a routine fix -- target the specific tables that need it.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- A specific query's plan regression is not resolved by a fresh ANALYZE -- escalate to query-optimization/analyze-query-plan for a deeper investigation.

## 12. Related Issues

- [stale-statistics](../../query-optimization/stale-statistics/README.md)
- [query-regression](../../performance/query-regression/README.md)
