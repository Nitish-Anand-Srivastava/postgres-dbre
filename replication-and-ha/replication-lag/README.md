# Replication Lag

**Category:** Replication and High Availability | **Workflow:** `replication-and-ha/replication-lag`

## 1. Problem Description

Investigates elevated replication lag -- either Aurora's native storage-layer reader lag, or standard PostgreSQL streaming/logical replication lag to an external consumer -- and helps distinguish the two, since they are measured and caused differently.

## 2. Typical Symptoms

- Application reading from a reader endpoint sees stale data relative to a recent write.
- CloudWatch AuroraReplicaLag metric elevated.
- An external logical replication subscriber (CDC, DMS) falling further behind.

## 3. Business Impact

- Elevated reader lag directly risks read-after-write consistency bugs for any feature relying on reader-endpoint routing (e.g. reading an order immediately after placing it) -- a correctness risk, not just a performance one, in a financial platform.

## 4. Possible Root Causes

- High write/WAL volume on the writer outpacing the reader's redo-apply rate.
- A long-running query on the reader itself blocking redo application (Aurora readers can experience apply delay from local query conflicts, similar in spirit to standard PostgreSQL recovery conflicts).
- Reader instance under-provisioned (smaller instance class) relative to the writer's write rate.
- For external logical replication: the subscriber itself is slow/down, or a network issue between publisher and subscriber.

## 5. Investigation Strategy

1. Confirm which kind of lag is being observed: Aurora reader lag (use aurora_replica_status()) vs. standard streaming/logical replication lag (use pg_stat_replication on the writer).
2. Check current WAL generation rate on the writer as a likely driver of reader lag.
3. Check for long-running queries on the specific lagging reader.
4. For external logical replication, check replication slot status for the specific subscriber.

## 6. Prerequisites

- pg_monitor role membership on both writer and reader instances.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_aurora_native_replica_lag.sql`](scripts/01_aurora_native_replica_lag.sql) -- Checks Aurora's native cluster-wide replica lag via the Aurora-specific function -- the correct source for reader lag on Aurora.
2. [`scripts/02_standard_streaming_replication.sql`](scripts/02_standard_streaming_replication.sql) -- Checks standard PostgreSQL streaming replication status from the writer, for any external physical/logical replica or CDC consumer (NOT Aurora readers).
3. [`scripts/03_writer_wal_generation.sql`](scripts/03_writer_wal_generation.sql) -- Checks current WAL generation rate on the writer, the primary driver of reader apply lag under high write volume.
4. [`scripts/04_reader_side_long_queries.sql`](scripts/04_reader_side_long_queries.sql) -- Checks for long-running queries on the specific lagging reader instance that could be delaying redo application.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Aurora readers share the same underlying distributed storage volume as the writer and receive redo log records through Aurora's internal storage-layer replication mechanism -- they do NOT stream WAL from the writer via standard PostgreSQL physical replication, so pg_stat_replication on the writer will show NO rows for Aurora reader instances even when readers exist and are healthy.
- Use `aurora_replica_status()` (callable from any instance in the cluster) or the CloudWatch `AuroraReplicaLag`/`AuroraReplicaLagMaximum`/`AuroraReplicaLagMinimum` metrics as the authoritative source for Aurora reader lag.

## 8. Interpretation Guide

- Aurora reader lag (from aurora_replica_status()) and standard PostgreSQL pg_stat_replication lag measure fundamentally different things and are not interchangeable -- do not use pg_stat_replication to explain Aurora reader lag; it will not show Aurora readers at all.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If a specific long-running query on the reader is blocking redo application, consider cancelling it after confirming impact (see incident-response/runaway-query for safety guidance, applied to the reader context).

**Short-term remediation** (hours to days):

- Reduce WAL-heavy write patterns identified via performance/high-iops's pgss_wal_heavy script.
- Consider a larger reader instance class if consistently under-provisioned relative to write volume.

**Long-term engineering fix** (days to weeks):

- For features requiring strict read-after-write consistency, route those specific reads to the writer endpoint rather than relying on eventual reader consistency, or implement application-level read-your-writes handling (e.g. a short-lived cache of just-written data).

## 10. Production Safety

- All investigation scripts are read-only.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Reader lag remains elevated with no identifiable query-level or WAL-volume cause -- open an AWS Support case, since this may indicate an Aurora storage-layer issue.

## 12. Related Issues

- [reader-lag-investigation](../reader-lag-investigation/README.md)
- [reader-performance](../reader-performance/README.md)
- [high-iops](../../performance/high-iops/README.md)
