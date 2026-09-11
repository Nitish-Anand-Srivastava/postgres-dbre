# Query Plan Regression

**Category:** Query Optimization | **Workflow:** `query-optimization/query-plan-regression`

## 1. Problem Description

A statement that was fast yesterday is slow today, and its text has not changed. The plan did. This workflow is built around comparison: it finds statements whose latency distribution has shifted, enumerates the things that can change a plan without changing a query (statistics, data volume, index state, configuration, parameter values, cached generic plans), and provides the runbook for capturing plan baselines so the next regression is diagnosed by comparison rather than by reconstruction.

## 2. Typical Symptoms

- A specific statement's latency stepped up at an identifiable moment, with no deployment of that code path.
- Latency is bimodal: most executions are fast, a minority are dramatically slower.
- A statement's mean execution time is stable while its maximum and standard deviation have grown sharply.
- Performance degraded immediately after a migration, a bulk load, an index change, a parameter change, or an Aurora failover.

## 3. Business Impact

- Plan regressions are abrupt rather than gradual: the plan flips and latency changes by an order of magnitude in a single moment, so an exchange can go from healthy to failing order placement without any warning trend.
- Because the query text did not change, the deploying team's first instinct is that the database broke, which costs time at exactly the wrong moment unless the evidence is ready.
- Regressions on the order-placement, balance-check, and withdrawal paths are immediately user-visible and, during volatility, revenue-affecting.

## 4. Possible Root Causes

- Statistics changed: an ANALYZE (manual or automatic) updated the planner's picture and it chose differently, for better or worse.
- Data volume or distribution crossed a threshold where the planner's cost comparison flipped between two plans.
- An index was added, dropped, or left invalid by a failed concurrent build, changing the available access paths.
- A configuration change: work_mem, random_page_cost, effective_cache_size, or an enable_* parameter altered in a parameter group.
- Parameter-value sensitivity: the same prepared statement is fast for typical values and slow for outliers such as the most liquid trading pair or the largest institutional account.
- A cached generic plan being used for a prepared statement where a custom plan would be far better (plan_cache_mode and the five-execution heuristic).
- An Aurora failover: the new writer has a cold cache and reset statistics counters, so both plan choice inputs and measured performance change at once.
- Table bloat or a physical reorganization altering correlation and therefore the attractiveness of ordered index scans.

## 5. Investigation Strategy

1. Find statements whose latency distribution is widest -- high standard deviation and a maximum far above the mean is the statistical signature of more than one plan.
2. Check whether planning time itself changed, which points at a different cause than execution-time regression.
3. Check statistics freshness and recency: an ANALYZE at the regression moment is a prime suspect, in either direction.
4. Check index state, including indexes left invalid by a failed build, which silently removes an access path.
5. Check configuration for drift, including parameters that were changed during a previous incident and never reverted.
6. Compare the current plan against the stored baseline, or establish that baseline now if none exists.

## 6. Prerequisites

- Role membership in pg_monitor (or pg_read_all_stats).
- pg_stat_statements, ideally not reset since before the regression -- an Aurora failover resets it and destroys the comparison.
- A stored plan baseline for the affected statement if one exists (from database-health/pre-deployment-check, or from the runbook in this workflow).
- The approximate time the regression began, correlated against the deployment, migration, parameter change, and failover timelines.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_latency_distribution_by_statement.sql`](scripts/01_latency_distribution_by_statement.sql) -- Finds statements whose execution time distribution is widest, the statistical signature of a plan change.
2. [`scripts/02_planning_time_check.sql`](scripts/02_planning_time_check.sql) -- Checks whether the regression is in planning time rather than execution time.
3. [`scripts/03_statistics_change_check.sql`](scripts/03_statistics_change_check.sql) -- Checks when statistics were last refreshed on the tables involved, in both directions.
4. [`scripts/04_index_state_check.sql`](scripts/04_index_state_check.sql) -- Checks whether an index change or an invalid index removed the access path the plan relied on.
5. [`scripts/05_configuration_drift_check.sql`](scripts/05_configuration_drift_check.sql) -- Checks planner and memory configuration for drift that could have changed the plan.
6. [`scripts/06_plan_baseline_comparison.md`](scripts/06_plan_baseline_comparison.md) -- Guarded runbook for comparing the current plan against a stored baseline, and for creating baselines when none exist.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- An Aurora failover resets pg_stat_statements, pg_stat_database, and every other in-memory statistics view on the promoted instance. A regression investigation that starts after a failover has no history to compare against unless a baseline was persisted beforehand.
- The promoted writer also starts with a cold buffer cache, so the first minutes after a failover show elevated latency that is not a plan regression at all. Check instance uptime before diagnosing anything else.
- Planner statistics are catalog data on the shared cluster volume and do survive a failover, so the plan itself should not change across one -- which is a useful discriminator between a genuine plan regression and a cache-warming effect.
- Parameter-group changes are applied cluster-wide and some require a reboot; a parameter that was changed days ago may only have taken effect at the reboot, making the regression's start time correlate with the reboot rather than with the change.

## 8. Interpretation Guide

- pg_stat_statements aggregates every execution of a normalized statement since the counters were reset, so a regression halfway through that window shows up as a raised maximum and standard deviation long before the mean moves noticeably. Do not wait for the mean.
- A high standard deviation relative to the mean means executions are not homogeneous: either two different plans are in use, or one plan performs very differently for different parameter values.
- Correlate the regression's start time with the four change timelines that can move a plan without touching code: deployments and migrations, ANALYZE and autoanalyze activity, index changes, and parameter-group changes. Aurora failovers are the fifth.
- A regression immediately after a failover may be a cold cache rather than a plan change at all: the new writer's buffer cache starts empty and warms over minutes to hours. Confirm instance uptime before concluding the plan changed.
- If the statement is a prepared statement executed more than five times, PostgreSQL may have switched from custom plans to a cached generic plan. That switch is invisible in pg_stat_statements and is a classic cause of a regression with no external change whatsoever.
- An invalid index removes an access path silently: the planner ignores it, the application keeps paying its write cost, and the plan reverts to a sequential scan. Always check for one after any migration.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If the regression started with a deployment and the rollback window is open, roll back first and diagnose afterwards.
- If an invalid index is the cause, the access path is currently missing -- plan an immediate concurrent rebuild.
- If stale statistics are the cause, a targeted ANALYZE frequently restores the previous plan within seconds.

**Short-term remediation** (hours to days):

- Rebuild any index left invalid by a failed concurrent build.
- Revert an unintended parameter change, or correct statistics for the mis-estimated table.
- For a parameter-sensitivity regression, consider forcing custom plans for that statement (plan_cache_mode = force_custom_plan, set at the narrowest possible scope) after confirming with a plan capture that a custom plan is genuinely better.

**Long-term engineering fix** (days to weeks):

- Capture and store plan baselines for the exchange's critical statements as part of the deployment pipeline, so a regression is a two-minute comparison rather than a multi-hour reconstruction.
- Alert on latency distribution (maximum and standard deviation) rather than on mean latency alone, so a bimodal regression is detected while only a minority of executions are affected.
- Include production-scale data in pre-production plan validation so volume-threshold flips are found before release.

## 10. Production Safety

- All .sql scripts here are read-only.
- Capturing the current plan for comparison uses plain EXPLAIN, which executes nothing and is safe at any time; EXPLAIN ANALYZE is only needed when estimated-versus-actual row counts are required, and is guarded accordingly. Deciding to actually execute a candidate production query is an operator judgement call, not something an investigation script may do on the operator's behalf. That is why every EXPLAIN ANALYZE step in this toolkit is a markdown runbook rather than a .sql file.
- Never disable a plan type (enable_nestloop, enable_hashjoin) as a production remedy for a regression: it is a diagnostic tool, and a cluster-wide setting distorts every other statement.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- A regression affects order placement, balance checks, withdrawals, or settlement -- escalate immediately and evaluate rollback in parallel with diagnosis.
- pg_stat_statements was reset (typically by a failover) and no stored baseline exists, so the regression cannot be confirmed from database evidence -- escalate to reconstruct it from application-side latency metrics.
- The plan reverts to the bad shape after every remediation, indicating a deeper estimation problem -- escalate to cardinality-estimation.

## 12. Related Issues

- [analyze-query-plan](../analyze-query-plan/README.md)
- [stale-statistics](../stale-statistics/README.md)
- [cardinality-estimation](../cardinality-estimation/README.md)
- [inefficient-index-usage](../inefficient-index-usage/README.md)
- [query-regression](../../performance/query-regression/README.md)
- [performance-after-deployment](../../performance/performance-after-deployment/README.md)
- [post-deployment-check](../../database-health/post-deployment-check/README.md)
