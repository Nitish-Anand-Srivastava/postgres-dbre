# Throughput Degradation

**Category:** Performance Issues | **Workflow:** `performance/throughput-degradation`

## 1. Problem Description

The number of transactions/queries the database successfully processes per second has dropped, even if individual query latency has not obviously changed -- for example, a batch job or ETL pipeline is completing fewer rows/sec than its established baseline, or overall xact_commit rate has fallen versus incoming request rate.

## 2. Typical Symptoms

- A batch/ETL job that normally completes in X minutes now takes significantly longer at the same input size.
- xact_commit rate (transactions/sec) has dropped while application-reported request volume has not.
- Growing backlog/queue depth in an upstream system feeding the database (e.g. a Kafka consumer lag growing against a DB sink).

## 3. Business Impact

- Throughput degradation on settlement/batch reconciliation jobs risks missed SLAs for downstream regulatory or partner reporting.
- If sustained, throughput degradation on the primary write path will eventually manifest as growing queue depth and, ultimately, dropped/rejected requests upstream.

## 4. Possible Root Causes

- Serialization: increased lock contention forcing transactions to run one-at-a-time instead of concurrently.
- Batch size regression: an ORM/batch job now issuing many small transactions instead of fewer larger ones (or vice versa, causing lock hold time to increase).
- Autovacuum/checkpoint contention consuming I/O and CPU that would otherwise serve application throughput.
- A downstream consumer (replica, CDC) falling behind and backpressuring writes if synchronous replication or a replication-slot-based consumer is involved.
- Connection pool exhaustion capping concurrent in-flight transactions below the workload's needs.

## 5. Investigation Strategy

1. Establish the current transaction commit rate and compare against the known baseline for this time of day/week.
2. Check for lock contention/serialization forcing effective single-threading of what should be concurrent transactions.
3. Check autovacuum and checkpoint activity as competing consumers of the same I/O/CPU budget.
4. Check connection headroom, since a capped pool directly caps achievable throughput regardless of per-transaction latency.
5. Check replication slot/WAL retention if a downstream consumer is suspected of backpressuring the writer.

## 6. Prerequisites

- A known throughput baseline (transactions/sec or job completion time) to compare against -- without one, this workflow can only establish current state, not confirm degradation.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_transaction_commit_rate.sql`](scripts/01_transaction_commit_rate.sql) -- Reports cumulative commit/rollback counters per database to compute a commit rate across two snapshots.
2. [`scripts/02_lock_serialization_check.sql`](scripts/02_lock_serialization_check.sql) -- Checks for lock waits that would force otherwise-concurrent transactions to serialize.
3. [`scripts/03_autovacuum_and_checkpoint_competition.sql`](scripts/03_autovacuum_and_checkpoint_competition.sql) -- Checks whether autovacuum or checkpoint activity is competing for the same resources as the throughput-sensitive workload.
4. [`scripts/04_connection_pool_headroom.sql`](scripts/04_connection_pool_headroom.sql) -- Checks whether the connection pool itself is capping achievable concurrency/throughput.
5. [`scripts/05_replication_slot_backpressure.sql`](scripts/05_replication_slot_backpressure.sql) -- Checks replication slot WAL retention, since a stalled logical replication consumer can backpressure the writer.

## 8. Interpretation Guide

- A falling xact_commit rate with stable or falling active session count suggests serialization (each transaction is individually fine, but fewer run concurrently) -- check locks.
- A falling xact_commit rate with a growing active session count suggests a resource bottleneck (CPU/IO) is now the limiting factor -- pivot to high-cpu/high-iops.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If a specific blocking session is identified, resolve it per concurrency-and-locking/blocked-queries.
- If connection pool exhaustion is capping throughput, temporarily raise pool size within max_connections headroom.

**Short-term remediation** (hours to days):

- Batch small transactions together (fewer, larger transactions) if per-transaction overhead is dominating.
- Reschedule or throttle competing maintenance (manual VACUUM/REINDEX) away from the batch window.

**Long-term engineering fix** (days to weeks):

- Redesign the batch/ETL job for partitioned, parallelizable processing (see partitioning/partition-performance).
- Establish throughput SLOs and alert on drift rather than relying on manual comparison against memory of past runs.

## 10. Production Safety

- All scripts are read-only.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Throughput degradation affects a regulatory/settlement deadline -- escalate immediately to database engineering leadership and compliance stakeholders.

## 12. Related Issues

- [high-database-load](../high-database-load/README.md)
- [transaction-contention](../../concurrency-and-locking/transaction-contention/README.md)
