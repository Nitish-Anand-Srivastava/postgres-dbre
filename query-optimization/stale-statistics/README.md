# Stale Planner Statistics

**Category:** Query Optimization | **Workflow:** `query-optimization/stale-statistics`

## 1. Problem Description

Planner statistics are a snapshot of the data taken by the last ANALYZE. When a table changes substantially after that snapshot -- a backfill, a migration, a surge of new trades during a volatility event, a bulk purge -- the planner keeps making decisions from a picture of the data that no longer exists. This workflow finds tables whose statistics have drifted, explains why autoanalyze did not catch them, and provides the guarded runbook for refreshing them safely.

## 2. Typical Symptoms

- A query plan changed for the worse shortly after a data migration, backfill, or bulk load, with no code deployment involved.
- A newly created or recently truncated-and-reloaded table performs terribly on its first queries.
- n_mod_since_analyze is very large relative to the table's row count, while last_analyze and last_autoanalyze are old or NULL.
- Estimates in EXPLAIN output that match the table's size from some point in the past rather than its size now.

## 3. Business Impact

- Stale statistics are the most common cause of a sudden plan regression on an exchange, and they strike hardest immediately after a migration -- the moment when the team is least able to distinguish a database problem from a release problem.
- During a volatility event, table contents can change faster in an hour than they normally do in a week, so statistics can go stale precisely when query performance matters most.
- The remedy is usually a single targeted ANALYZE taking seconds to minutes, which makes an unfixed stale-statistics problem an expensive incident to leave running.

## 4. Possible Root Causes

- A bulk load, backfill, or migration completed without a follow-up ANALYZE.
- autovacuum_analyze_scale_factor (default 0.1) being a percentage: on a 500 million row trades table, 10% means 50 million modifications before autoanalyze triggers.
- Autoanalyze starved because autovacuum workers are all busy, or because the table is repeatedly skipped in favour of more urgent anti-wraparound work.
- A per-table storage option disabling autovacuum or autoanalyze for the table, often set during a past incident and never reverted.
- A newly created table with no statistics at all until the first ANALYZE runs.
- A table restored from a dump or created by a migration tool, where statistics are never carried over and must be built fresh.

## 5. Investigation Strategy

1. Rank tables by modifications since their last ANALYZE, relative to their size.
2. Look specifically for tables that have never been analyzed, or that have very low analyze counters despite heavy write volume.
3. Check the autovacuum and autoanalyze configuration, including per-table storage options that may have disabled it.
4. Inspect the actual stored statistics for a suspect table to see how far they have drifted from reality.
5. Refresh statistics for the specific tables identified, following the guarded runbook.

## 6. Prerequisites

- Role membership in pg_monitor (or pg_read_all_stats) for the investigation.
- Table ownership, MAINTAIN privilege, or pg_maintain membership to execute the ANALYZE described in the runbook.
- The list of tables recently affected by a migration or bulk operation, if this investigation follows a deployment.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_statistics_freshness_ranked.sql`](scripts/01_statistics_freshness_ranked.sql) -- Ranks tables by how far their statistics have drifted since the last ANALYZE.
2. [`scripts/02_analyze_counters_and_never_analyzed.sql`](scripts/02_analyze_counters_and_never_analyzed.sql) -- Surfaces tables that have never been analyzed or are analyzed far less often than their write volume warrants.
3. [`scripts/03_autoanalyze_configuration.sql`](scripts/03_autoanalyze_configuration.sql) -- Shows the global autoanalyze settings and any per-table overrides that change or disable them.
4. [`scripts/04_stored_statistics_for_table.sql`](scripts/04_stored_statistics_for_table.sql) -- Inspects the actual stored distribution statistics for one suspect table.
5. [`scripts/05_refresh_statistics_safely.md`](scripts/05_refresh_statistics_safely.md) -- Guarded runbook for refreshing planner statistics on specific tables with ANALYZE.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Statistics are catalog data on the shared cluster volume, so an ANALYZE on the writer is immediately visible to every reader. They also survive a failover, unlike pg_stat_statements counters.
- ANALYZE must run on the writer: readers are in continuous recovery and cannot write catalog rows.
- autovacuum_analyze_scale_factor and default_statistics_target are DB cluster parameter group settings on Aurora; per-table overrides via ALTER TABLE ... SET are the targeted alternative and require no parameter-group change or reboot.

## 8. Interpretation Guide

- n_mod_since_analyze counts inserts, updates, and deletes since the last ANALYZE. Judge it as a percentage of n_live_tup rather than in absolute terms: 5 million modifications is nothing on a 500 million row table and catastrophic on a 2 million row one.
- last_analyze being NULL while last_autoanalyze is populated is normal -- it just means no human has ever run ANALYZE manually. Both being NULL on a table with rows means the planner has never had real statistics for it.
- A high analyze_count with still-stale statistics means autoanalyze is running but the scale factor is too coarse for the table's size; lower the per-table scale factor rather than analyzing manually on a schedule.
- A reloptions value containing autovacuum_enabled=false disables autoanalyze for that table as well. This is occasionally correct for a transient staging table and is almost always wrong on a permanent exchange table.
- ANALYZE is much cheaper than VACUUM: it reads a sample of pages rather than the whole table, takes a lock that does not block reads or writes, and never rewrites data. Running it on a specific table during trading hours is a normal, low-risk operation.
- Statistics do not exist for a table's TOAST storage or for expressions unless an expression index or extended statistics object provides them -- a table can look fully analyzed and still leave the planner blind to a predicate's selectivity.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Run a targeted ANALYZE on the specific tables implicated in the current performance problem, following the runbook in this workflow.

**Short-term remediation** (hours to days):

- Lower autovacuum_analyze_scale_factor for the largest, highest-churn tables so autoanalyze triggers on a sensible absolute number of modifications rather than on a percentage of an enormous table.
- Remove any per-table option that disabled autovacuum or autoanalyze, unless there is a current, documented reason for it.
- Add an explicit ANALYZE step to the end of every migration that loads or bulk-modifies data.

**Long-term engineering fix** (days to weeks):

- Make post-migration ANALYZE an automated, non-optional step of the deployment pipeline rather than a runbook instruction someone must remember.
- Monitor statistics staleness as a first-class metric alongside vacuum debt, with per-table thresholds for the exchange's critical tables.
- Partition the very large tables so that autoanalyze operates on partition-sized units and triggers at a useful frequency without any scale-factor tuning.

## 10. Production Safety

- Every .sql script in this workflow is read-only; none of them runs ANALYZE.
- ANALYZE is deliberately provided only as a guarded markdown runbook. It is a maintenance operation against a specific table, and choosing when to run it against a production exchange table is an operator decision requiring change management -- an investigation script must never issue it implicitly.
- ANALYZE takes a SHARE UPDATE EXCLUSIVE lock: it does not block reads or writes, but it does conflict with concurrent VACUUM, another ANALYZE, and most ALTER TABLE forms on the same table.
- Never run a bare database-wide ANALYZE on a production exchange cluster as a routine remedy: it analyzes every table including the largest, generating substantial unnecessary I/O.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- A table is so large that a full ANALYZE has a material I/O cost and needs a scheduled window.
- Statistics go stale again within hours of every refresh, meaning the write rate has outgrown the current autoanalyze configuration entirely.
- A plan regression persists after fresh, correctly-sized statistics -- escalate to cardinality-estimation and then to analyze-query-plan.

## 12. Related Issues

- [cardinality-estimation](../cardinality-estimation/README.md)
- [query-plan-regression](../query-plan-regression/README.md)
- [analyze-query-plan](../analyze-query-plan/README.md)
- [analyze-statistics](../../vacuum-and-autovacuum/analyze-statistics/README.md)
- [post-deployment-check](../../database-health/post-deployment-check/README.md)
