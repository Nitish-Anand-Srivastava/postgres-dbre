# Building Durable Slow-Query Observability

**Category:** Observability | **Workflow:** `observability/slow-query-observability`

## 1. Problem Description

How to build standing, always-on visibility into slow and expensive queries -- centered on pg_stat_statements as the primary continuous instrumentation, plus guidance on configuring statement-level logging (log_min_duration_statement, auto_explain) through Aurora's DB parameter group model. This is durable observability infrastructure, not a one-off diagnostic pass: the goal is that the next slow-query incident starts with existing data to query, not with turning on instrumentation after the fact.

## 2. Typical Symptoms

- No active symptom -- this workflow is used to establish or audit standing query observability, not to investigate a specific slow query (see performance/slow-queries for that).
- An incident review discovers that the specific slow statement's history could not be reconstructed because pg_stat_statements had been reset, or logging was never capturing it.
- A new cluster or a new database within an existing cluster needs the same query-level observability the rest of the fleet already has.

## 3. Business Impact

- Without pg_stat_statements running continuously, every slow-query investigation starts from zero: no history of which statements are normally slow, so distinguishing 'normal for this workload' from 'new regression' after an incident already occurred is close to guesswork.
- log_min_duration_statement, correctly tuned, is often the only way to see complete text and exact parameters of an actually slow statement (pg_stat_statements normalizes and can truncate query text) -- without it, root-causing a specific slow occurrence can be impossible after the fact.
- auto_explain with timing enabled captures the *actual* execution plan a slow statement used in production, which is frequently different from what EXPLAIN produces when run manually afterward against a since-changed data distribution.

## 4. Possible Root Causes

- Not a failure workflow -- this is about the presence and correctness of instrumentation, not a specific query problem.
- The most common gap this workflow closes: pg_stat_statements not enabled at all (it requires a parameter-group change and a reboot on Aurora, so it is sometimes deferred and forgotten), or enabled but with a query-text-store size/eviction setting too small for the workload's query diversity.
- log_min_duration_statement left at its default (disabled or very high) because logging every slow statement's full text has a real I/O and log-volume cost that was never explicitly budgeted for.

## 5. Investigation Strategy

1. Confirm pg_stat_statements is installed and actively tracking (script 01 detects and reports if it is not).
2. Establish the top-total-time and top-mean-time views as the two complementary rankings every review should check.
3. Add the temp-file/I/O-heavy view to catch queries whose cost is memory/I/O pressure rather than raw latency.
4. Decide and document the log_min_duration_statement threshold and auto_explain configuration for this cluster's parameter group, understanding the Aurora reboot/logging-volume tradeoffs first (script 04).
5. Revisit the pg_stat_statements query-text-store sizing (pg_stat_statements.max) periodically -- a workload with high query-shape diversity (many distinct ad hoc or ORM-generated statements) can silently evict older, still-relevant entries.

## 6. Prerequisites

- Role membership in pg_monitor (or pg_read_all_stats), plus SELECT on pg_stat_statements once it is installed.
- pg_stat_statements in the Aurora DB cluster parameter group's shared_preload_libraries (requires a reboot to apply) and CREATE EXTENSION pg_stat_statements run in each database that needs it, both as change-managed actions outside this workflow's SQL scope.
- Agreement with the platform/logging team on the log volume budget before enabling verbose statement logging cluster-wide -- log_min_duration_statement set too low on a high-throughput exchange writer can itself become an I/O and log-ingestion cost problem.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_top_statements_by_total_time.sql`](scripts/01_top_statements_by_total_time.sql) -- Ranks normalized statements by cumulative execution time -- the primary 'where does the database spend its time' view.
2. [`scripts/02_top_statements_by_mean_time.sql`](scripts/02_top_statements_by_mean_time.sql) -- Ranks statements by mean execution time (restricted to a minimum call count) to find individually slow statements regardless of total volume.
3. [`scripts/03_temp_file_and_io_heavy_statements.sql`](scripts/03_temp_file_and_io_heavy_statements.sql) -- Ranks statements by temp file and shared-buffer I/O volume, surfacing memory/I/O pressure independent of raw latency.
4. [`scripts/04_configuring_log_min_duration_and_auto_explain.md`](scripts/04_configuring_log_min_duration_and_auto_explain.md) -- Runbook for configuring log_min_duration_statement and auto_explain through Aurora's DB parameter group model.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- pg_stat_statements requires shared_preload_libraries to include it at the Aurora DB cluster parameter group level, which requires a reboot (and therefore a failover in a multi-instance cluster) to apply -- plan this like any other maintenance action, not as a quick same-session change.
- Aurora does not support ALTER SYSTEM for most parameters, including log_min_duration_statement and auto_explain settings -- these are configured through the DB cluster/instance parameter group (see script 04's runbook) and some require a reboot to take effect.
- An Aurora failover resets pg_stat_statements' accumulated counters on the promoted instance -- any 'this got faster/slower' comparison spanning a failover is comparing across a reset window and is not a valid conclusion on its own.
- Aurora's CloudWatch Logs integration is the mechanism for actually retrieving log-based output (log_min_duration_statement, auto_explain) from an Aurora instance -- there is no local filesystem log access the way there is on a self-managed server.

## 8. Interpretation Guide

- Rank by total_exec_time to find where the database spends its aggregate time (a cheap statement executed millions of times can dominate); rank by mean_exec_time (with a minimum call-count filter) to find individually slow statements that may not yet be frequent enough to dominate the total.
- A statement's presence in the temp-file/I/O-heavy view alongside a merely moderate execution time is still worth investigating -- it is consuming memory/I/O capacity disproportionate to its apparent latency cost, and that capacity is shared with every other query on the instance.
- pg_stat_statements normalizes literal values out of query text (parameters become placeholders), which is exactly what allows similar statements to aggregate together -- but it also means the view alone cannot show which specific parameter value was slow; that is what log_min_duration_statement and auto_explain are for.
- All pg_stat_statements counters are cumulative since the last reset (extension creation, explicit pg_stat_statements_reset(), or an Aurora failover) -- always check whether a comparison period spans a reset before concluding a query got faster or slower.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- This workflow builds standing observability; it does not remediate a specific slow query -- once a statement is identified, route to performance/slow-queries or query-optimization/analyze-query-plan for plan-level remediation.

**Short-term remediation** (hours to days):

- If pg_stat_statements is not yet installed, schedule the parameter-group change and reboot, and treat the extension's creation as the starting point for this cluster's query-history baseline.
- If pg_stat_statements.max is undersized for this workload's query-shape diversity, raise it in the parameter group (also requires a reboot) rather than accepting silent eviction of older statement entries.

**Long-term engineering fix** (days to weeks):

- Establish a recurring (weekly or per-release) review of the top-total-time and top-mean-time views as a standing practice, not only a reactive one triggered by an incident.
- Feed the top-statement views into the dashboard layout proposed in dashboard-recommendations so query-level trends are visible continuously.

## 10. Production Safety

- The three read-only scripts in this workflow are strictly read-only and safe to run at any time, including during an active incident.
- pg_stat_statements itself adds a small, generally negligible per-query overhead for tracking; it is designed to run continuously in production and is not something to enable only temporarily.
- Enabling log_min_duration_statement or auto_explain (script 04) changes what gets written to the instance's logs and therefore has a real I/O and log-ingestion cost at a low threshold on a high-throughput writer -- read the runbook's guidance on choosing a threshold before applying it, and treat the change itself as a parameter-group change requiring the same review as any other.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- pg_stat_statements is found to not be installed anywhere in the fleet -- this is a standing observability gap, not an incident, but should be treated as high-priority infrastructure work given how much it limits every future slow-query investigation.
- A statement responsible for a large share of total_exec_time on the order-placement, balance-check, withdrawal, or settlement path -- escalate to performance/slow-queries with this workflow's output attached.
- pg_stat_statements.max eviction is suspected (a previously-seen statement is missing from the current view with no reset having occurred) -- escalate to raise the setting before more history is lost.

## 12. Related Issues

- [postgres-metrics](../postgres-metrics/README.md)
- [performance-insights](../performance-insights/README.md)
- [wait-event-analysis](../wait-event-analysis/README.md)
- [slow-queries](../../performance/slow-queries/README.md)
- [analyze-query-plan](../../query-optimization/analyze-query-plan/README.md)
- [query-plan-regression](../../query-optimization/query-plan-regression/README.md)
