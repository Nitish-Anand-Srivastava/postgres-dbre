# Wait Event Analysis

**Category:** Observability | **Workflow:** `observability/wait-event-analysis`

## 1. Problem Description

A deep dive on pg_stat_activity's wait_event_type / wait_event columns -- what each wait event category actually means, how to read the aggregated and per-session views, and how this same taxonomy is what Performance Insights uses to color its DB load chart. Wait events are the most direct answer PostgreSQL can give to 'what is this session waiting for right now', and reading them correctly is usually faster than guessing from symptoms alone.

## 2. Typical Symptoms

- Sessions are active but query latency is elevated with no single obvious cause -- wait event analysis is the fastest way to classify whether the cause is CPU, locking, I/O, or something else entirely.
- Performance Insights' DB load view shows a dominant wait event and the corresponding live session/query detail is needed to act on it.
- A specific wait_event value is unfamiliar and its meaning needs to be confirmed before deciding whether it indicates a problem.

## 3. Business Impact

- Correctly classifying a wait event in the first minute of an investigation (Lock vs. IO vs. IPC vs. CPU) sends the on-call DBA directly to the right dedicated workflow instead of a broad, slower elimination process across every possible cause.
- Some wait events (Lock, IPC) directly indicate that other sessions are being blocked right now -- on an exchange's order or ledger path, recognizing this immediately is the difference between a two-minute fix and a cascading pool-exhaustion incident.
- Other wait events (Client, most of Activity) are entirely expected and never indicate a database-side problem -- misreading these as a database issue wastes investigation time that should go toward the application or network layer instead.

## 4. Possible Root Causes

- Not a failure workflow -- this documents how to interpret a signal, not a specific failure mode.
- The most common misinterpretation this workflow corrects: treating any non-null wait_event as inherently a problem, when several wait event types (Client, Activity) are the fully expected, healthy state for a connection-pooled idle or background-worker session.

## 5. Investigation Strategy

1. Get the aggregated wait event summary first, to see the overall shape of current load before looking at any individual session.
2. Break the aggregation down further by state (active vs. idle-in-transaction vs. idle) to separate genuine contention from expected idle waiting.
3. Drill into per-session detail for the specific wait_event_type/wait_event combination that dominates, to identify the exact sessions and queries responsible.
4. Use the wait event type reference to confirm the meaning of any specific wait_event value before deciding whether it is actionable.
5. Cross-reference against Performance Insights' DB load view (performance-insights) for the same classification over a longer historical window than a live snapshot can show.

## 6. Prerequisites

- Role membership in pg_monitor (or pg_read_all_stats).
- Familiarity with this workflow's wait event type reference (script 04), especially before an incident, since reading it for the first time under pressure is slower than having it already understood.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_current_wait_event_summary.sql`](scripts/01_current_wait_event_summary.sql) -- Aggregates current backends by wait event type/name, joined to pg_wait_events for a plain-language description.
2. [`scripts/02_wait_event_contention_by_type_and_state.sql`](scripts/02_wait_event_contention_by_type_and_state.sql) -- Breaks wait events down further by session state, to separate genuine contention from expected idle waiting.
3. [`scripts/03_per_session_wait_event_detail.sql`](scripts/03_per_session_wait_event_detail.sql) -- Row-per-session detail for every backend currently registering a wait event, with plain-language description and query text.
4. [`scripts/04_wait_event_type_reference.md`](scripts/04_wait_event_type_reference.md) -- Reference guide to each wait_event_type category's meaning, typical causes, and whether it is normally actionable.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- The wait_event_type/wait_event taxonomy on Aurora PostgreSQL is the same one standard community PostgreSQL 17 exposes -- Aurora does not remap or rename these values, which is exactly why Performance Insights' wait-event coloring lines up directly with a live pg_stat_activity query.
- IO wait events on Aurora represent a round trip to the distributed storage layer rather than a local disk read -- a given IO wait event's latency profile can differ meaningfully from the same wait event on self-managed PostgreSQL running against local NVMe storage, so do not assume self-managed PostgreSQL latency expectations transfer directly.
- pg_wait_events (joined in scripts 01 and 03 for plain-language descriptions) is a standard PostgreSQL 17 catalog view and is fully available on Aurora.

## 8. Interpretation Guide

- wait_event_type is the broad category (Lock, LWLock, BufferPin, Activity, Client, Extension, IPC, IO, Timeout); wait_event is the specific instance within that category -- always read both together, since the same wait_event name can theoretically exist informationally differently across versions while the type rarely does.
- Lock: the session is waiting on a heavyweight lock (row, table, or object level) held by another session -- this is directly actionable via concurrency-and-locking/blocked-queries and blocking_sessions_detail-style joins, and is never the expected steady state for more than a brief moment.
- LWLock and BufferPin: internal PostgreSQL synchronization primitives -- occasional brief occurrences are normal; a sustained concentration of sessions here usually indicates contention on a specific internal structure (e.g. a hot buffer) rather than an application-level lock, and needs a targeted investigation rather than the standard blocking-session approach.
- IO: the session is waiting on a storage read/write -- on Aurora this specifically means a round trip to the distributed storage layer, and a sustained concentration here is the SQL-level signal that corresponds to elevated DiskQueueDepth/VolumeReadIOPs in CloudWatch.
- IPC: inter-process communication, commonly parallel query workers waiting on each other, or a session waiting on a checkpoint/vacuum coordination point -- usually benign and self-resolving, but a sustained large count warrants checking what parallel or maintenance operations are in flight.
- Client and most of Activity: the session is waiting on the client application (a query result already sent, or the connection is simply idle) -- this is the expected state for the majority of connections in a healthy, pooled application at any given moment and is not itself a finding.
- Timeout: the session is in a deliberate sleep (e.g. pg_sleep, or a background process on its configured interval) -- confirm which specific wait_event this is before assuming it means anything is wrong.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- This workflow is diagnostic, not remedial -- once the dominant wait event and responsible sessions are identified, route to the workflow that owns that specific wait event category (see Related Issues).

**Short-term remediation** (hours to days):

- For a Lock-dominated finding, resolve the blocking session per concurrency-and-locking/blocked-queries rather than treating the wait event alone as sufficient diagnosis.
- For an IO-dominated finding, corroborate against CloudWatch's storage-layer metrics (cloudwatch) before concluding the storage layer itself is the bottleneck versus a specific query's access pattern (tables-and-indexes/sequential-scan-investigation).

**Long-term engineering fix** (days to weeks):

- Add wait-event distribution to the standing dashboard (dashboard-recommendations) so a shift in the normal mix is visible as a trend, not only discovered during an active incident.
- Use Performance Insights' longer retention (performance-insights) to establish this cluster's normal wait-event baseline by time of day/week, so a live snapshot can be judged against an actual expectation rather than intuition.

## 10. Production Safety

- Every script in this workflow is strictly read-only and safe to run at any time, including during a severe incident -- these are exactly the queries to run first when load is elevated and the cause is unknown.
- The per-session detail script includes query text, which may include sensitive literal values if pg_stat_activity is configured to show full statements -- handle output with the same care as any other query-text-containing diagnostic in this repository.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Lock wait events dominate for more than a few minutes -- escalate immediately to concurrency-and-locking/lock-contention or blocked-queries; on wallet/ledger tables this risks a financial-operation-visible delay.
- IO wait events dominate with no corresponding CloudWatch storage-layer metric explanation -- escalate to performance/high-iops.
- A wait_event value not covered by the reference in script 04 appears prominently -- confirm its meaning against the current PostgreSQL 17 documentation before dismissing or escalating it, since new wait events are occasionally added between minor versions.

## 12. Related Issues

- [performance-insights](../performance-insights/README.md)
- [postgres-metrics](../postgres-metrics/README.md)
- [blocked-queries](../../concurrency-and-locking/blocked-queries/README.md)
- [lock-contention](../../concurrency-and-locking/lock-contention/README.md)
- [high-iops](../../performance/high-iops/README.md)
- [high-database-load](../../performance/high-database-load/README.md)
