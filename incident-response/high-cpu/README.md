# High CPU -- First Response Checklist

**Category:** Incident Response | **Workflow:** `incident-response/high-cpu`

## 1. Problem Description

CloudWatch is alarming on CPUUtilization for the writer or a reader and somebody needs an answer in the next five minutes. This is the rapid triage version: establish whether the CPU is doing useful work, find the sessions responsible, and decide what to cut. The deep-dive analysis of why a query is expensive belongs in `performance/high-cpu`; do not start there while an alarm is firing.

## 2. Typical Symptoms

- CPUUtilization sustained above 80-90% on the writer or a specific reader.
- Trading, order-cancel and balance-read latency climbing in step with the CPU curve.
- Active session count rising without any corresponding rise in completed transactions.
- Performance Insights showing Average Active Sessions well above the instance's vCPU count with CPU as the dominant component.
- Readers at high CPU while the writer looks fine, or the exact reverse -- the asymmetry is itself a strong clue.

## 3. Business Impact

- A CPU-saturated writer queues every order, cancel and wallet write behind runnable work, so the exchange's entire critical path slows at once.
- Sustained saturation eventually makes the instance unresponsive to new connections, converting a performance incident into an availability incident.
- Risk and compliance checks that gate withdrawals begin to time out, which either blocks customer withdrawals or, far worse, causes them to be skipped if the application fails open.

## 4. Possible Root Causes

- A small number of expensive queries (a bad plan, a missing index, an unbounded scan) consuming most of the runnable time.
- A retry storm: an upstream service timing out and re-issuing the same query many times over, multiplying the load that caused the original timeout.
- Legitimate traffic growth or a market-volatility burst exceeding the current instance class.
- Connection churn: thousands of short-lived connections forcing constant backend startup, parsing and planning overhead.
- Maintenance work colliding with peak traffic: aggressive autovacuum, an index build, or a bulk backfill.
- Expensive per-row work in the query path -- user-defined functions, JSONB processing, regex predicates, or heavy sorting.
- Parallel query fan-out: a handful of statements each spawning workers and collectively oversubscribing every core.

## 5. Investigation Strategy

1. Snapshot overall session load first, so you know whether this is many small units of work or a few large ones.
2. Check the wait-event mix straight away -- CPU-bound work shows as active sessions with no wait event, and anything else means the CPU number is a symptom of a different problem.
3. List the longest-running active queries and look for repetition of the same statement shape.
4. Pull the top statements by total execution time from pg_stat_statements, which attributes cumulative cost far better than any instantaneous snapshot can.
5. Check whether autovacuum or another maintenance operation is competing for the same cores.
6. Act: cancel, shed, or scale -- and if the cause is a genuinely expensive query shape, hand it to the performance deep-dive rather than tuning it live.

## 6. Prerequisites

- `pg_monitor` role membership.
- `pg_stat_statements` for script 04 (the script degrades to a notice if it is absent).
- CloudWatch access to confirm which instances are actually hot -- there is no SQL query that returns CPU percentage, so this must come from outside the database.
- The instance class and its vCPU count, so you can judge whether the active session count is plausibly saturating it.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_session_load_snapshot.sql`](scripts/01_session_load_snapshot.sql) -- Sizes the load in one query: how many sessions exist, in which states, and how long the longest have been running.
2. [`scripts/02_cpu_versus_wait_breakdown.sql`](scripts/02_cpu_versus_wait_breakdown.sql) -- Separates genuine CPU-bound work from sessions that are merely waiting -- the check that decides whether this is really a CPU incident.
3. [`scripts/03_top_active_queries_now.sql`](scripts/03_top_active_queries_now.sql) -- Lists the active queries running longest right now, so the dominant statement shape can be identified in seconds.
4. [`scripts/04_top_statements_by_total_time.sql`](scripts/04_top_statements_by_total_time.sql) -- Attributes cumulative execution time to specific statements, which an instantaneous snapshot cannot do.
5. [`scripts/05_maintenance_competing_for_cpu.sql`](scripts/05_maintenance_competing_for_cpu.sql) -- Checks whether autovacuum or other maintenance work is competing with application traffic for the same cores.
6. [`scripts/06_cpu_mitigation_actions.md`](scripts/06_cpu_mitigation_actions.md) -- Guarded runbook for cutting CPU load fast: cancelling the dominant sessions, stopping a retry storm, deferring maintenance, and deciding to scale.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- There is no SQL query that returns CPU utilization: CPUUtilization is an instance-level CloudWatch metric. The closest SQL-visible proxies are the count of active sessions with no wait event and cumulative execution time from pg_stat_statements.
- Aurora does not run the vacuum and checkpoint workload exactly as community PostgreSQL does, but autovacuum workers are still ordinary backends consuming instance CPU, and they are visible in pg_stat_activity like any other session.
- Performance Insights' Average Active Sessions compared against the instance's vCPU count is the fastest way to judge saturation: AAS consistently above vCPU count means work is queueing for CPU, regardless of what the raw CPU percentage looks like.

## 8. Interpretation Guide

- Active sessions with NULL wait events are the true CPU signal. If the active count is around or above the vCPU count and those sessions are not waiting on anything, the instance is genuinely CPU-bound.
- Active sessions that are mostly waiting on Lock or IO mean the CPU number is collateral damage; fixing CPU will not fix the incident.
- A few statements accounting for the bulk of total_exec_time in pg_stat_statements is the most actionable finding available -- it names the fix.
- A very high calls count with a small mean_exec_time is a volume problem, not a query problem, and is very often a retry storm rather than genuine user demand.
- Autovacuum workers running on large hot tables during peak hours can account for a surprising share of CPU, and unlike application work they can usually be deferred safely for a short period.
- Readers hot while the writer is idle means read traffic is being routed at them faster than they can serve it; add capacity or rebalance rather than investigating the writer.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Cancel the specific dominant backends after confirming ownership, per the runbook in this workflow -- cancel, never terminate, unless cancel has demonstrably failed.
- Ask the owning service to disable the offending code path or feature flag if the same statement immediately reappears from new sessions; cancelling backends cannot outrun an application loop.
- Route eligible read traffic to the reader endpoint if the writer is the hot instance and the reads are genuinely tolerant of replica lag.
- Defer competing maintenance work (index builds, backfills, manual vacuum) until the CPU curve is back under control.

**Short-term remediation** (hours to days):

- Fix the plan for the top offenders identified in script 04, following the performance and query-optimization workflows.
- Put a transaction-mode pooler in front of the highest-churn services to remove connection-setup and planning overhead.
- Tune autovacuum on the hottest tables so it runs more often and more cheaply rather than rarely and expensively during peak hours.

**Long-term engineering fix** (days to weeks):

- Establish a documented scaling runbook tied to sustained Average Active Sessions rather than to raw CPU percentage, which is a lagging and misleading signal on its own.
- Move analytical and reporting consumers permanently off the writer.
- Add per-service query budgets and circuit breakers upstream, so a retry storm cannot convert a small slowdown into full CPU saturation.

## 10. Production Safety

- Scripts 01-05 are read-only and safe to run while the instance is saturated; they are catalog reads and add negligible load.
- Script 06 is a guarded manual runbook -- read it before executing anything in it.
- Do not restart the instance to 'reset' CPU. You lose the buffer cache, every in-flight order write fails, and the workload that caused the saturation returns within seconds against a cold cache.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- CPU remains above 90% for more than 15 minutes despite mitigation, with customer-visible impact.
- The cause is a retry storm from an upstream service -- escalate to that team immediately; this cannot be fixed from inside the database.
- The workload is legitimate and the instance class is simply undersized -- a scaling decision is required beyond on-call authority.
- Both the writer and every reader are saturated simultaneously, which points at a cluster-wide or storage-layer problem worth an AWS support case.

## 12. Related Issues

- [production-triage](../production-triage/README.md)
- [sudden-latency-spike](../sudden-latency-spike/README.md)
- [runaway-query](../runaway-query/README.md)
- [high-cpu](../../performance/high-cpu/README.md)
- [comprehensive-health-check](../../database-health/comprehensive-health-check/README.md)
