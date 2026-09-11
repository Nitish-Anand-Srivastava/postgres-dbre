# High CPU Utilization

**Category:** Performance Issues | **Workflow:** `performance/high-cpu`

## 1. Problem Description

Aurora instance-level CPU utilization (as reported by CloudWatch `CPUUtilization`) is sustained above a healthy threshold (commonly >80-90% for several minutes), risking query queuing, increased latency, and eventual request timeouts across every service that depends on the database.

## 2. Typical Symptoms

- CloudWatch CPUUtilization alarm on the writer or a reader instance.
- API latency (p95/p99) increasing across multiple services simultaneously.
- Order placement / trade matching latency increasing.
- Increasing number of active sessions in pg_stat_activity without a proportional increase in throughput.
- Performance Insights showing high Average Active Sessions (AAS) with CPU as the dominant wait.

## 3. Business Impact

- Trading and order execution latency directly affects fill quality and user trust in a low-latency exchange.
- Sustained high CPU risks cascading timeouts in upstream services (API gateways, matching engine, risk checks).
- If CPU saturation persists, Aurora may throttle or the instance may become unresponsive, risking a full outage.

## 4. Possible Root Causes

- Query-level: a new or regressed query plan (missing index, stale statistics, changed data distribution) causing CPU-heavy operations (sorts, hashes, nested loops over large sets).
- Volume-level: legitimate traffic growth or a burst (market volatility event) exceeding provisioned instance capacity.
- Concurrency-level: lock contention causing spin/retry behavior, or an excessive number of parallel workers per query.
- Maintenance-level: autovacuum/ANALYZE running heavily on large tables concurrently with peak traffic.
- Connection-level: connection storm causing excessive context switching and parsing/planning overhead (especially without a pooler / prepared statements).
- Extension/function-level: expensive user-defined functions, JSON/JSONB processing, or regex-heavy WHERE clauses.
- Infrastructure-level: undersized instance class for current workload; needs vertical scaling or read offloading.

## 5. Investigation Strategy

1. Confirm the scope: is this one instance (writer only, one reader, or all readers) or cluster-wide?
2. Identify overall session load and how much of it is 'active' vs. waiting on locks/IO (broad view).
3. Identify the specific queries currently consuming CPU (active queries with runtime and query text).
4. Cross-reference with pg_stat_statements to find historically expensive queries, not just this instant's snapshot.
5. Check wait events to distinguish true CPU-bound work from lock/IO waits that only look like load.
6. Check for lock contention that could be causing retries or serialization overhead.
7. Check table/index health (sequential scans, missing indexes, stale statistics, bloat) as a root cause of expensive plans.
8. Correlate with recent deployments, schema changes, or known traffic events (see performance-after-deployment, sudden-performance-degradation).

## 6. Prerequisites

- `pg_stat_statements` extension created in the target database for script 03 (falls back to pg_stat_activity-only analysis if unavailable).
- `pg_monitor` (or `pg_read_all_stats`) role membership for the connecting user.
- AWS Console/CloudWatch access to confirm instance-level CPUUtilization and Performance Insights Top SQL/Top Waits (see docs/aurora-postgresql/performance-insights-and-cloudwatch.md).

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_identify_database_load.sql`](scripts/01_identify_database_load.sql) -- Cluster-wide session/state overview to establish overall load before drilling in.
2. [`scripts/02_identify_active_queries.sql`](scripts/02_identify_active_queries.sql) -- Lists currently active queries running longer than a threshold, to identify what is actively consuming CPU right now.
3. [`scripts/03_identify_expensive_queries.sql`](scripts/03_identify_expensive_queries.sql) -- Top statements by total execution time from pg_stat_statements, to find the historically dominant CPU consumers, not just this instant's snapshot.
4. [`scripts/04_check_wait_events.sql`](scripts/04_check_wait_events.sql) -- Aggregates current wait events to confirm whether load is genuinely CPU-bound vs. lock/IO-bound.
5. [`scripts/05_check_lock_contention.sql`](scripts/05_check_lock_contention.sql) -- Confirms or rules out lock contention as a secondary/contributing factor to elevated CPU (e.g. spin-heavy retry logic).
6. [`scripts/06_check_table_index_health.sql`](scripts/06_check_table_index_health.sql) -- Checks for sequential-scan-heavy tables and stale statistics that commonly cause CPU-expensive plans.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- CPUUtilization is an instance-level CloudWatch metric, not a PostgreSQL catalog value -- there is no SQL query that returns 'CPU percent used'; the closest SQL-visible proxy is active session count and query-level exec-time from pg_stat_statements.
- Aurora Performance Insights' 'Average Active Sessions' (AAS) view decomposed by wait type is generally a faster way to distinguish CPU-bound from lock/IO-bound load than reconstructing it from pg_stat_activity snapshots alone.

## 8. Interpretation Guide

- A large number of 'active' sessions with no wait_event (NULL) genuinely running CPU-bound work is the clearest DB-side CPU signal.
- A large number of sessions with a non-null wait_event (especially Lock or IO) is NOT primarily a CPU problem even though CloudWatch CPU may still be elevated from context switching -- follow the concurrency-and-locking workflows instead.
- A handful of queries dominating pg_stat_statements total_exec_time with a high mean_exec_time and high calls is the most actionable finding -- prioritize plan/index fixes for those first.
- High seq_scan counts on large tables combined with the above is strong evidence of a missing index or a regressed plan.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If one or a few runaway queries dominate: consider cancelling (`pg_cancel_backend`) -- not terminating -- the specific backend(s) after confirming with the owning team, per incident-response/runaway-query.
- If traffic is legitimately elevated (e.g. market volatility): add read replicas / route eligible read traffic to reader endpoint to offload the writer.
- If an Aurora instance class is undersized for a sustained new baseline: scale the writer/reader instance class (requires brief failover for writer resize on some paths -- confirm with AWS documentation for zero-downtime options).

**Short-term remediation** (hours to days):

- Add or adjust indexes for the specific expensive queries identified in pg_stat_statements/EXPLAIN.
- Tune connection pooling (PgBouncer) to reduce planning/parsing overhead from very high connection churn.
- Schedule autovacuum/ANALYZE more aggressively on high-churn tables to keep plans efficient (see vacuum-and-autovacuum).

**Long-term engineering fix** (days to weeks):

- Introduce query result caching or read-replica routing for read-heavy, latency-tolerant endpoints.
- Revisit schema/partitioning strategy for tables driving the most CPU-heavy scans (see partitioning/).
- Establish CPU/AAS-based autoscaling or a documented vertical-scaling runbook tied to capacity forecasts (see storage-and-capacity/capacity-forecasting).

## 10. Production Safety

- All investigation scripts in this workflow are read-only.
- Do not run ANALYZE across every table as a blind remediation step; target specific tables identified in the investigation.
- Do not terminate backends without following incident-response/runaway-query safety guidance.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- CPU remains >90% for more than 15 minutes despite mitigations, with visible customer-facing latency impact.
- Root cause appears to be outside the database (application bug, retry storm) -- loop in application/SRE teams immediately rather than continuing DB-only investigation.
- Suspected undersized instance class requiring a scaling decision beyond on-call authority.

## 12. Related Issues

- [high-database-load](../high-database-load/README.md)
- [slow-queries](../slow-queries/README.md)
- [lock-contention](../../concurrency-and-locking/lock-contention/README.md)
- [high-cpu](../../incident-response/high-cpu/README.md)
