# High Query/Transaction Latency

**Category:** Performance Issues | **Workflow:** `performance/high-latency`

## 1. Problem Description

End-to-end database call latency (as observed by the application or APM) has increased, without necessarily a CPU, IOPS, or lock signal being obviously dominant. This workflow is the general entry point for 'the database feels slow' reports and routes to the more specific workflow once the dominant cause is found.

## 2. Typical Symptoms

- Application/APM-reported p95/p99 database call latency increase.
- Increase in average query duration in pg_stat_statements without a single obvious cause.
- Trading/order API latency creeping upward gradually rather than spiking suddenly.

## 3. Business Impact

- Latency directly affects competitiveness in a low-latency trading environment -- even modest increases can push an exchange out of acceptable execution-speed tolerances.
- Gradual latency creep is easy to normalize/ignore until it crosses an SLA threshold; catching it early avoids a harder future incident.

## 4. Possible Root Causes

- Any of: CPU saturation, lock contention, IOPS saturation, connection pool exhaustion, network/client-side factors, or a genuine plan regression.
- Increased network round trips per logical operation (N+1 query patterns from an application-level change).
- Connection setup/teardown overhead if connections are not being pooled/reused efficiently.

## 5. Investigation Strategy

1. Start broad: session/state overview and wait event composition.
2. Check pg_stat_statements for statements whose mean_exec_time has increased.
3. Check lock contention and connection headroom as common latency amplifiers that are not visible in a single query's plan.
4. Check replication lag if the latency is specifically reported against reader-routed traffic.
5. If none of the above show a clear signal, treat this as network/application-side and hand off to the owning team with the evidence gathered.

## 6. Prerequisites

- pg_stat_statements for the statement-level breakdown.
- Knowledge of whether the affected traffic is writer-routed or reader-routed, to scope scripts 01-04 to the correct instance.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_session_and_wait_overview.sql`](scripts/01_session_and_wait_overview.sql) -- Broad session/state and wait-event snapshot to orient the investigation.
2. [`scripts/02_statement_latency_trends.sql`](scripts/02_statement_latency_trends.sql) -- Statements with the highest mean execution time, called frequently enough to be a real trend rather than noise.
3. [`scripts/03_lock_wait_check.sql`](scripts/03_lock_wait_check.sql) -- Checks for blocked sessions as a latency amplifier that would not show up in a query's own plan.
4. [`scripts/04_connection_headroom.sql`](scripts/04_connection_headroom.sql) -- Checks connection utilization, since pool exhaustion manifests to the application as latency (waiting for a connection) rather than a slow query.
5. [`scripts/05_replication_lag_if_reader.sql`](scripts/05_replication_lag_if_reader.sql) -- If the affected traffic is reader-routed, checks Aurora replica lag via the cluster-native function.

## 8. Interpretation Guide

- Wait event composition dominated by Lock -> concurrency-and-locking; dominated by IO -> high-iops/storage-and-capacity; dominated by nothing in particular but connection count is near max_connections -> connections/connection-exhaustion.
- If reader-routed traffic is affected and replication lag is elevated, the reported 'latency' may actually be read-after-write staleness/retry behavior at the application layer, not raw query latency -- see replication-and-ha/reader-lag-investigation.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Route affected traffic away from a specifically degraded instance (reader) if the issue is isolated to one node.
- Apply the specific remediation from whichever pivot workflow (locking/IOPS/connections/replication) the investigation points to.

**Short-term remediation** (hours to days):

- Fix the specific statements identified with elevated mean_exec_time via indexing or rewriting.
- Increase reader fleet size or tune pooler settings if connection-level overhead is contributing materially.

**Long-term engineering fix** (days to weeks):

- Establish latency SLOs per critical query/endpoint and alert on drift before it becomes customer-visible.
- Review architecture for opportunities to reduce round trips (batching, caching) for latency-critical paths.

## 10. Production Safety

- All scripts are read-only.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- No database-side signal found after completing this workflow -- hand off to application/network/SRE with the gathered evidence rather than continuing to search inside the database.
- Latency increase correlates with a specific reader instance -- escalate for potential instance-level AWS issue investigation.

## 12. Related Issues

- [high-iops](../high-iops/README.md)
- [lock-contention](../../concurrency-and-locking/lock-contention/README.md)
- [reader-lag-investigation](../../replication-and-ha/reader-lag-investigation/README.md)
