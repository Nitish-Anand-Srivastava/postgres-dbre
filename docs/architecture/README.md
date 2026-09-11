# Architecture

How Aurora PostgreSQL is put together, and why that shapes the way this
toolkit investigates problems. This is background reading for the
`docs/aurora-postgresql/` differences guide and for every workflow that
reasons about writers, readers, storage, or failover.

## 1. Cluster shape

An Aurora PostgreSQL cluster is not "PostgreSQL with a different storage
engine bolted on" -- it separates compute from storage in a way that
changes what "replication," "checkpoint," and "disk I/O" mean operationally.

```text
                          Aurora Cluster
                          ───────────────────────────────────────
 Applications                                                    
 ───────────┐             ┌───────────┐        ┌───────────┐
 Cluster     │──writes──▶ │  Writer   │        │  Reader 1 │
 endpoint    │            │ Instance  │        │ Instance  │
 ───────────┘             └─────┬─────┘        └─────┬─────┘
 ───────────┐                   │                     │
 Reader      │──reads─────────────────────┐           │
 endpoint    │                            ▼           ▼
 ───────────┘                    ┌───────────────────────────┐
                                  │   Distributed Storage      │
                                  │  (6 copies / 3 AZ, quorum   │
                                  │      read & write)          │
                                  └───────────────────────────┘
```

Key structural facts that differ from a self-managed PostgreSQL + streaming
replication setup:

* **One shared, distributed storage volume.** All instances in the cluster
  (one writer, zero or more readers) share the same underlying cluster
  volume. There is no per-instance local data directory being replayed from
  WAL shipped over the network in the traditional sense.
* **Storage is replicated, not the database instance.** Aurora replicates
  data six ways across three Availability Zones at the storage layer. A
  write is durable once a quorum (4 of 6) of storage nodes acknowledge it.
* **Readers replay redo records, not physical WAL files.** Reader instances
  receive redo log records from storage and apply them to their own buffer
  cache to stay close to the writer's state. This is why reader lag is
  reported in milliseconds via `aurora_replica_status()` rather than by
  comparing WAL LSNs the way `pg_stat_replication` does upstream.
* **Crash recovery is fast and storage-driven.** Because storage already
  contains redo records, Aurora does not replay a local WAL from the last
  checkpoint the way standalone PostgreSQL does after a crash; recovery is
  typically sub-30-seconds regardless of instance size.

## 2. Endpoints

| Endpoint type | Points at | Used for |
| --- | --- | --- |
| Cluster (writer) endpoint | Current writer instance | All write traffic; DDL; strongly-consistent reads |
| Reader endpoint | Load-balanced across available reader instances | Read scaling; connection count is divided across readers, not sticky |
| Custom endpoint | An operator-defined subset of instances | Workload isolation (e.g., routing a reporting workload to two specific readers) |
| Instance endpoint | One specific instance | Targeted diagnostics; pinning a session to a specific reader during an investigation |

Investigation workflows that compare "writer vs. reader" behavior (see
`replication-and-ha/`) should connect to **instance endpoints** explicitly
rather than the reader endpoint, so results are not shuffled across
instances mid-investigation.

## 3. Failover

* Failover promotes an existing reader to writer; it does not build a new
  instance. Typical failover completion is on the order of tens of
  seconds, dominated by DNS propagation of the cluster endpoint and
  application reconnect behavior, not by crash recovery time.
* Applications must handle a full reconnect (not just a retry against the
  same TCP connection) after failover. Connection poolers that hold
  long-lived idle connections against the writer endpoint are the most
  common source of "the database recovered but the app is still down"
  incidents.
* See `replication-and-ha/failover-investigation/` and
  `replication-and-ha/failover-readiness/` for investigation workflows, and
  `performance/performance-after-failover/` for diagnosing degraded
  behavior that persists after a failover completes.

## 4. Buffer cache and instance sizing

Each instance (writer or reader) still has its own local buffer cache
(`shared_buffers`) sized from instance memory, even though storage is
shared. This matters operationally:

* A freshly promoted reader (new writer) starts with a cold cache relative
  to the previous writer's working set, which can look like a performance
  regression immediately after failover even though the query plans have
  not changed.
* Readers can have different cache "temperatures" from each other depending
  on the read traffic they have been receiving, which is one reason two
  readers can show different latency for the same query.

## 5. Where to go next

* Aurora-specific behavioral differences from community PostgreSQL:
  `docs/aurora-postgresql/README.md`.
* The safety model for running any script against this architecture:
  `docs/production-safety/README.md`.
* General investigation methodology that assumes this architecture:
  `docs/investigation-methodology/README.md`.
