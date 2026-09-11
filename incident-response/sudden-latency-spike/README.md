# Sudden Latency Spike

**Category:** Incident Response | **Workflow:** `incident-response/sudden-latency-spike`

## 1. Problem Description

Database response times jumped sharply and recently -- p99 order placement, balance reads or ledger writes went from milliseconds to seconds within minutes -- without any obvious outage. This workflow is the fast triage that separates the four candidate causes (blocking, a plan or workload change, resource saturation, or pressure from checkpoint/IO/temp activity) quickly enough to act on the answer, rather than the deep single-query analysis that belongs in the performance category.

## 2. Typical Symptoms

- p95/p99 latency for database calls steps up sharply at an identifiable minute rather than degrading gradually.
- Order placement and cancellation acknowledgements slow down while throughput stays flat or falls.
- Active session count in pg_stat_activity climbs because each request now holds its connection longer.
- Aurora Performance Insights shows Average Active Sessions rising with a visible change in the wait-event mix.
- Market-data or risk consumers start lagging because their reads now queue behind slower writes.

## 3. Business Impact

- Latency on the order path directly degrades fill quality; during volatile markets a few hundred extra milliseconds is the difference between a filled and a missed order, and customers notice immediately.
- Slower ledger and wallet writes push deposit and withdrawal confirmations past their SLA, generating support volume and, if sustained, regulatory attention.
- Upstream services with their own timeouts begin failing and retrying, which adds load to the very database that is already slow -- latency spikes are self-amplifying if not cut quickly.

## 4. Possible Root Causes

- Concurrency: a new blocking chain, so most of the added latency is lock wait rather than work.
- Workload: a traffic surge (market event, a newly enabled feature, a retry storm from an upstream service) pushing the instance past its comfortable concurrency point.
- Plan/statistics: a plan flipped after an autoanalyze or a data-distribution change, and one hot statement now costs an order of magnitude more.
- Resource: CPU or IO saturation from a heavy batch job, a large index build, or aggressive autovacuum running during peak trading hours.
- Memory: queries spilling sorts and hashes to temp files because work_mem is too small for the new data volume.
- Checkpoint/WAL: a burst of write activity forcing frequent checkpoints and stalling foreground writes.
- Replication: readers falling behind, so read traffic routed to them returns stale or slow results and the application retries against the writer.

## 5. Investigation Strategy

1. Take a single broad activity snapshot first -- how many sessions, in what states, and how long has the longest one been running.
2. Read the wait-event mix immediately after. This is the fastest branch point in the whole workflow: Lock waits mean blocking, IO waits mean resource pressure, and an absence of waits with high active counts means genuine CPU-bound work.
3. List the longest-running active queries to see whether one statement shape dominates the new latency.
4. Check for a blocking chain, because a single blocker explains a cluster-wide latency step change more often than any other single cause.
5. Check checkpoint, IO and temp-file pressure, which explains latency that appears in write paths without any corresponding blocking.
6. Compare current statement timing against pg_stat_statements history to identify the specific statements whose mean time has moved.
7. Decide and act: unblock, shed or cancel the offending work, or escalate to the matching deep-dive workflow.

## 6. Prerequisites

- `pg_monitor` role membership.
- `pg_stat_statements` for script 06 (the workflow still functions without it -- the script prints a notice rather than failing).
- A latency baseline you can compare against: yesterday's p99 at the same time of day, not a vague sense of normal.
- The deployment and market-event timeline for the last hour, so correlation is possible at all.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_activity_overview.sql`](scripts/01_activity_overview.sql) -- Broad session/state snapshot to size the spike before drilling into any single cause.
2. [`scripts/02_wait_event_mix.sql`](scripts/02_wait_event_mix.sql) -- Reads the current wait-event distribution -- the fastest branch point for deciding which cause to pursue.
3. [`scripts/03_longest_active_queries.sql`](scripts/03_longest_active_queries.sql) -- Lists the currently active queries running longest, to see whether one statement shape dominates the new latency.
4. [`scripts/04_blocking_snapshot.sql`](scripts/04_blocking_snapshot.sql) -- Checks whether the added latency is simply lock wait, which is the most common single explanation for a cluster-wide step change.
5. [`scripts/05_checkpoint_io_and_temp_pressure.sql`](scripts/05_checkpoint_io_and_temp_pressure.sql) -- Checks checkpoint frequency, per-backend-type IO and temp-file volume -- the resource-pressure explanations for latency that has no blocking behind it.
6. [`scripts/06_statement_timing_shift.sql`](scripts/06_statement_timing_shift.sql) -- Compares current statement timings against pg_stat_statements history to find the specific statements whose cost has moved.
7. [`scripts/07_latency_mitigation_actions.md`](scripts/07_latency_mitigation_actions.md) -- Guarded runbook for the actions that actually cut a latency spike short: cancelling the dominant work, shedding non-critical load, and time-boxing statements.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Aurora's storage layer means write latency is a network round trip to a quorum of storage nodes rather than a local disk flush, so a latency spike on writes can come from the storage fleet rather than from anything visible in the instance's own catalogs -- correlate with the CloudWatch WriteLatency and DiskQueueDepth metrics before concluding the cause is in your workload.
- Performance Insights retains per-second wait-event history, so it can show you the exact minute the wait-event mix changed. Reconstructing that from pg_stat_activity snapshots is far slower and much less precise.
- Aurora reader instances serve reads from the same storage volume as the writer, so a latency spike caused by storage-layer pressure appears on readers and the writer simultaneously -- that pattern rules out most query-level explanations immediately.

## 8. Interpretation Guide

- Wait events are the branch point. A Lock-dominated mix means go straight to lock-storm; an IO-dominated mix means resource pressure; LWLock or IPC waits suggest internal contention and usually accompany a concurrency level the instance cannot absorb.
- Many active sessions with NULL wait events and short individual runtimes is a throughput problem, not a single-query problem -- the instance is doing a lot of small work well, just more of it than it has capacity for.
- One statement shape appearing repeatedly in the long-running list with a mean time far above its historical value is a plan regression until proven otherwise.
- A jump in temp_bytes together with slow sorts points at work_mem, and it is usually triggered by data growth rather than by a code change -- the query did not change, the volume did.
- A high pct_forced_checkpoints means write volume is outrunning max_wal_size, and foreground writes are paying for it.
- If every signal here looks normal, the latency is probably not in the database: check the pooler, the network path and the application's own garbage collection before continuing here.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If blocking dominates, resolve the root blocker using the lock-storm workflow -- that single action usually restores latency across every affected service at once.
- If one runaway statement dominates, cancel it per the runaway-query runbook after confirming ownership.
- If load is legitimately elevated, shed or throttle the least business-critical traffic first (reporting, analytics, backfills) rather than degrading the order path for everyone.
- If a batch job or index build is competing with peak traffic, pause or cancel it -- it can be rerun in a quiet window; the trading day cannot.

**Short-term remediation** (hours to days):

- Refresh statistics on the specific tables backing the regressed statements rather than analysing everything blindly.
- Add or correct the index that the regressed statement needs, following the schema-changes concurrent build pattern.
- Raise work_mem for the specific role running the spilling workload rather than globally, so a per-connection increase cannot exhaust instance memory.
- Move reporting and analytical consumers to the reader endpoint so they cannot contend with the order path again.

**Long-term engineering fix** (days to weeks):

- Add latency SLOs per query shape with alerting on step changes, so the next spike is detected by monitoring rather than by customers.
- Introduce plan-stability checks in CI for the handful of statements on the trading and settlement hot path.
- Schedule batch, backfill and index maintenance work in explicit low-volume windows enforced by tooling, not by convention.

## 10. Production Safety

- Scripts 01-06 are read-only and safe to run repeatedly during the spike; taking two snapshots a minute apart is often more informative than one.
- Script 07 is a guarded manual runbook whose actions cancel work or change live configuration -- read it fully first.
- Do not restart the instance or fail over to 'clear' a latency spike. It discards the buffer cache and makes latency worse for several minutes, on top of the outage the failover itself causes.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Latency stays elevated for more than 15 minutes with customer-visible impact on the order or withdrawal path.
- The spike coincides with a deployment that cannot be rolled back without a data migration -- involve the deploying team and database engineering jointly, immediately.
- The dominant wait events are Aurora-internal (IO or IPC waits with no application-side explanation) -- open an AWS support case in parallel with continuing the investigation.
- Latency degradation is accompanied by rising replica lag on every reader, which suggests a writer-side saturation problem with cluster-wide reach.

## 12. Related Issues

- [production-triage](../production-triage/README.md)
- [lock-storm](../lock-storm/README.md)
- [runaway-query](../runaway-query/README.md)
- [application-timeouts](../application-timeouts/README.md)
- [high-cpu](../../performance/high-cpu/README.md)
- [blocked-queries](../../concurrency-and-locking/blocked-queries/README.md)
