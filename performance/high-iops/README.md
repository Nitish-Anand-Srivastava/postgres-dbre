# High IOPS / Storage I/O Saturation

**Category:** Performance Issues | **Workflow:** `performance/high-iops`

## 1. Problem Description

The Aurora instance or cluster storage is showing elevated I/O operations per second (CloudWatch VolumeReadIOPS/VolumeWriteIOPS or ReadIOPS/WriteIOPS) or is approaching a provisioned/burst I/O limit, causing increased read/write latency at the storage layer.

## 2. Typical Symptoms

- CloudWatch VolumeReadIOPS/VolumeWriteIOPS or ReadIOPS/WriteIOPS elevated versus baseline.
- Increased ReadLatency/WriteLatency CloudWatch metrics.
- Queries that were previously fast now show elevated planning-independent latency (same plan, slower execution).
- Increased buffer cache miss rate (shared_blks_read growing much faster than shared_blks_hit in pg_stat_statements).

## 3. Business Impact

- Storage I/O saturation increases the latency of every operation touching disk, not just one query -- broad, hard-to-isolate degradation.
- On Aurora, sustained IOPS also directly affects the AWS bill (I/O-Optimized vs. standard billing) and can be an early indicator of a capacity/pricing-tier decision.

## 4. Possible Root Causes

- Working set no longer fits in shared_buffers / OS cache: queries that used to hit the buffer cache now read from Aurora storage.
- A specific query or batch job scanning far more data than necessary (missing index, missing partition pruning).
- Autovacuum or manual VACUUM/ANALYZE reading large tables concurrently with peak traffic.
- Checkpoint activity writing a large volume of dirty buffers (see checkpoint_timeout/max_wal_size tuning).
- Excessive temp file spill activity from undersized work_mem.
- A logical replication slot or CDC consumer falling behind, forcing WAL retention and re-reads.

## 5. Investigation Strategy

1. Check the cache hit ratio at the database level to see how much read traffic is actually reaching storage.
2. Identify statements generating the most shared buffer reads (proxy for I/O) via pg_stat_statements.
3. Check per-backend-type I/O breakdown (pg_stat_io) to see whether autovacuum/checkpointer/backends are the dominant I/O source.
4. Check checkpoint frequency/duration, since checkpoint writes are a major, tunable source of write I/O.
5. Check temp file usage, since spilling sorts/hashes to disk directly consumes IOPS.
6. Check replication slot WAL retention, since a stuck consumer can force additional storage I/O.

## 6. Prerequisites

- pg_stat_statements for script 02.
- track_io_timing enabled (check via key settings snapshot) for I/O timing columns to be populated rather than zero.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_database_cache_hit_ratio.sql`](scripts/01_database_cache_hit_ratio.sql) -- Computes the buffer cache hit ratio per database as a proxy for how much read traffic is reaching storage.
2. [`scripts/02_top_io_generating_queries.sql`](scripts/02_top_io_generating_queries.sql) -- Identifies statements generating the most shared buffer reads, the strongest query-level proxy for storage I/O.
3. [`scripts/03_io_by_backend_type.sql`](scripts/03_io_by_backend_type.sql) -- Breaks down I/O by backend type (client backend, autovacuum, checkpointer, etc.) using pg_stat_io.
4. [`scripts/04_checkpoint_frequency.sql`](scripts/04_checkpoint_frequency.sql) -- Checks checkpoint frequency and the ratio of forced vs. scheduled checkpoints, a major source of write I/O.
5. [`scripts/05_temp_file_io.sql`](scripts/05_temp_file_io.sql) -- Checks temp file generation, which directly consumes read/write IOPS for spilled sorts/hashes.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Aurora storage IOPS and throughput are metrics reported by CloudWatch at the cluster/instance level; PostgreSQL catalogs only expose logical proxies (cache hit ratio, buffer reads, WAL bytes), never the actual physical storage IOPS number itself.

## 8. Interpretation Guide

- A falling cache hit ratio over time at constant traffic volume indicates the working set has outgrown shared_buffers/instance memory -- consider a larger instance class or reducing the scanned data volume (indexes, partitioning, archiving).
- If pg_stat_io shows checkpointer/autovacuum as the dominant writer, the fix is scheduling/timeout tuning, not query optimization.
- If a small number of queries dominate shared_blks_read, that is the highest-leverage fix (index/partition pruning) before considering instance-class changes.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Route read traffic to reader endpoint(s) if the writer specifically is I/O saturated and readers have headroom.
- If a specific batch/reporting query is the driver, pause or reschedule it off-peak.

**Short-term remediation** (hours to days):

- Add missing indexes / partition pruning support to reduce scanned data volume for the top offending queries.
- Tune checkpoint_timeout/max_wal_size (via the Aurora cluster parameter group) to smooth write I/O instead of bursty checkpoints.

**Long-term engineering fix** (days to weeks):

- Evaluate Aurora I/O-Optimized configuration if IOPS cost/volume is consistently high (an AWS Console/billing decision, not a SQL change).
- Archive/partition large historical tables that are the primary source of scanned data volume (see archival-and-data-lifecycle, partitioning).

## 10. Production Safety

- All investigation scripts are read-only.
- Do not change checkpoint_timeout/max_wal_size without testing recovery-time implications -- larger values reduce write I/O but increase crash-recovery replay time.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- IOPS sustained near the storage subsystem's practical ceiling for the instance class with no single fixable query -- this is a capacity/billing decision, escalate to database engineering leadership.
- Suspected Aurora storage-layer issue (not explained by any workload change) -- open an AWS Support case.

## 12. Related Issues

- [high-latency](../high-latency/README.md)
- [wal-generation](../../storage-and-capacity/wal-generation/README.md)
- [temp-file-investigation](../../query-optimization/temp-file-investigation/README.md)
