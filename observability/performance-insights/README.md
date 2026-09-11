# Using AWS Performance Insights Alongside SQL Diagnostics

**Category:** Observability | **Workflow:** `observability/performance-insights`

## 1. Problem Description

AWS Performance Insights (PI) samples pg_stat_activity roughly once per second and aggregates it into Average Active Sessions (AAS) broken down by wait event, SQL statement, user, and host -- the same underlying source data this repository's SQL-level scripts read on demand, but continuously recorded, retained, and rendered as a stacked timeline. This workflow explains how to read PI's DB load view correctly, when to reach for it before a SQL session, and how to cross-reference its findings back against the live catalog queries in this repository to confirm and drill into what it shows.

## 2. Typical Symptoms

- Overall database load or latency is elevated and the specific cause is not yet known -- the classic entry point for PI's DB load view before drilling into any specific SQL script.
- An incident needs a historical view of load at a specific past timestamp (a spike ten minutes ago) that a live pg_stat_activity query can no longer see.
- high-database-load or a similar performance investigation needs a wait-event-centric breakdown of exactly where active sessions were spending their time.

## 3. Business Impact

- PI's continuous one-second sampling captures a wait-event-level breakdown of a transient spike that a live SQL query, run only after someone notices a problem, has already missed by the time anyone looks.
- The DB load view's wait-event coloring turns 'the database feels slow' into a specific, actionable category (CPU vs. Lock vs. IO vs. IPC) in seconds, without needing to construct or remember the equivalent catalog query first.
- Because PI requires no additional load on the database itself (it samples via the RDS/Aurora control plane, not a client connection), it remains available and readable even when the database is under enough load or connection pressure that opening a new psql session is itself difficult.

## 4. Possible Root Causes

- Not a failure workflow -- this explains how to use an observability tool, not a specific failure mode.
- The most common misuse this workflow corrects: treating PI's DB load number as a single global 'health score' rather than reading its wait-event/SQL/user breakdown, which is where the actual diagnostic value is.

## 5. Investigation Strategy

1. Open the PI console (or the GetResourceMetrics API) for the instance and time window in question and read the DB load view's stacked wait-event breakdown before anything else -- it costs nothing to check and often narrows the search immediately.
2. If DB load is dominated by CPU, corroborate with a live wait-event snapshot (script 01) and CPU-focused SQL diagnostics (performance/high-cpu) rather than assuming PI's classification alone is the full picture.
3. If DB load is dominated by a non-CPU wait event (Lock, IO, IPC), switch PI's view to break down by that wait event and by SQL statement/queryid to identify the specific statement or session responsible.
4. Cross-reference the queryid PI surfaces against pg_stat_statements directly (script 02, or slow-query-observability) to get the full query text and execution statistics PI's UI may truncate.
5. For a currently ongoing spike, corroborate PI's historical view with the live per-session detail in wait-event-analysis, since PI aggregates while a live query shows individual sessions and their exact query text.

## 6. Prerequisites

- Performance Insights enabled on the target DB instance (it is enabled by default for new Aurora PostgreSQL instances since a certain console/CLI default, but existing instances may have it off -- see script 03 for how to check and enable it).
- IAM permission to view Performance Insights for the instance (pi:GetResourceMetrics / pi:DescribeDimensionKeys or console equivalent) -- this is an AWS IAM permission, separate from any PostgreSQL role.
- Role membership in pg_monitor (or pg_read_all_stats) for the SQL-side cross-reference scripts.
- pg_stat_statements installed for the queryid cross-reference step (PI's own sampling does not require it, but confirming what a queryid actually is does).

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_current_wait_event_snapshot.sql`](scripts/01_current_wait_event_snapshot.sql) -- Aggregates current backends by wait event, the same taxonomy Performance Insights uses to color its DB load chart.
2. [`scripts/02_active_session_load_by_query.sql`](scripts/02_active_session_load_by_query.sql) -- Groups currently active sessions by query_id and wait event, approximating PI's Top SQL / DB load by SQL breakdown from live catalog data.
3. [`scripts/03_enabling_and_interpreting_performance_insights.md`](scripts/03_enabling_and_interpreting_performance_insights.md) -- Runbook for confirming/enabling Performance Insights on a DB instance and reading its DB load view correctly during an investigation.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Performance Insights on Aurora PostgreSQL reports at the DB instance level, not the cluster level -- a reader under load and the writer under load show up as separate PI resources; check the correct instance identifier, especially right after a failover changed which instance is the writer.
- PI's wait-event taxonomy matches PostgreSQL's own pg_stat_activity.wait_event_type/wait_event columns directly on Aurora, unlike some managed-database services that remap wait events to a proprietary taxonomy -- cross-referencing PI's chart against a live wait_events_summary() query (script 01) works because they are the same underlying classification.
- A failover changes which instance is the writer; PI's per-instance view does not automatically follow the writer role, so after a failover, re-identify which PI resource corresponds to the new writer before comparing pre/post-failover load.

## 8. Interpretation Guide

- DB load is measured in Average Active Sessions: a DB load of 1.0 for a given period means, on average, one session was found active (not idle) each time PI sampled. Compare DB load against the instance's vCPU count -- sustained DB load meaningfully above vCPU count means sessions are queuing for something, not just using available CPU in parallel.
- The wait-event coloring in PI's stacked chart is the same wait_event_type taxonomy pg_stat_activity itself exposes (CPU, Lock, LWLock, IO, IPC, Timeout, Client, Extension, BufferPin) -- wait-event-analysis in this same category documents what each one means in detail.
- PI's 'Top SQL' and 'Top Waits' tabs are ranked by their contribution to DB load (AAS), which is a different ranking from pg_stat_statements' total_exec_time -- a statement can dominate DB load by being active-and-waiting very often without having the highest cumulative execution time, and vice versa.
- PI retains one week of data at the default (free) retention tier and up to two years at the long-term (paid) tier -- for a suspected recurring pattern (weekly settlement, month-end reconciliation), confirm the retention tier before assuming historical data is still available.
- PI samples via the RDS/Aurora control plane at roughly one-second granularity; it can slightly under- or over-represent extremely short-lived sessions compared to a continuous trace, so treat single-second spikes as directional rather than exact.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- This workflow is diagnostic, not remedial -- once PI or the SQL cross-reference identifies the responsible wait event and statement, route to the dedicated workflow that owns that failure mode (performance/high-cpu, concurrency-and-locking/lock-contention, and so on).

**Short-term remediation** (hours to days):

- If PI is not yet enabled on a production instance, enable it (script 03) so the next incident has this historical view available -- there is no reason to run without it given its low overhead and low cost at the default 7-day retention.
- Bookmark or export the specific PI console URL/time-range for an incident's review, since the console view is easiest to share with a team that does not have SQL access.

**Long-term engineering fix** (days to weeks):

- Enable the long-term (paid) PI retention tier on clusters where recurring monthly/quarterly patterns (settlement, reconciliation, compliance reporting) need to be compared across cycles longer than a week.
- Fold PI's DB load metric into the dashboard proposed in dashboard-recommendations, so wait-event trends are visible continuously rather than only pulled up during an active incident.

## 10. Production Safety

- Performance Insights itself imposes negligible overhead on the database -- it samples via the RDS/Aurora control plane, not through a client connection, so viewing it never adds query load.
- Every SQL script in this workflow is strictly read-only and safe to run at any time, including during an active incident.
- Enabling Performance Insights on an existing instance (script 03) may require a brief modification window on some older instance classes -- read the runbook's caveats before scheduling it, and prefer doing so outside peak trading hours the first time.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- DB load sustained meaningfully above the instance's vCPU count for an extended period, with no corresponding drop in application throughput explaining it as expected -- escalate to performance/high-database-load.
- PI's Top Waits view is dominated by Lock wait events for more than a few minutes -- escalate to concurrency-and-locking/lock-contention immediately rather than waiting for a live SQL session to confirm it.
- PI shows a load spike that has already ended by the time it is noticed and no live session data remains -- this is exactly the scenario PI exists for; do not conclude 'nothing to investigate' just because a live pg_stat_activity query now looks clean.

## 12. Related Issues

- [postgres-metrics](../postgres-metrics/README.md)
- [wait-event-analysis](../wait-event-analysis/README.md)
- [cloudwatch](../cloudwatch/README.md)
- [slow-query-observability](../slow-query-observability/README.md)
- [high-database-load](../../performance/high-database-load/README.md)
- [lock-contention](../../concurrency-and-locking/lock-contention/README.md)
