# Native PostgreSQL Metrics Worth Monitoring Continuously

**Category:** Observability | **Workflow:** `observability/postgres-metrics`

## 1. Problem Description

The core set of native PostgreSQL statistics views and catalogs that a continuously-running monitoring pipeline (a scheduled collector, an exporter feeding Prometheus/Grafana, or a periodic health-check job) should read from, and why each one matters for an exchange-scale Aurora PostgreSQL 17+ deployment. This workflow is the SQL-level foundation everything else in this category builds on: performance-insights and cloudwatch add AWS-managed context on top of these same underlying signals, and dashboard-recommendations proposes how to lay them out for a team to watch continuously.

## 2. Typical Symptoms

- No active symptom -- this is the reference list used when standing up a new monitoring pipeline, onboarding a new cluster, or auditing what an existing dashboard is (or is not) already covering.
- An incident review reveals that a metric which would have given early warning was not being collected at all.
- A new engineer asks 'what should I actually be watching on this database' and needs a concrete, prioritized answer rather than 'everything'.

## 3. Business Impact

- Nearly every database incident that reaches an exchange's trading path was observable in these views minutes to days before it became user-visible -- connection headroom, dead tuple accumulation, and XID age all move slowly and predictably if someone (or something) is watching.
- Cheap, high-signal counters (cache hit ratio, rollback rate, deadlocks) catch a large fraction of degraded-but-not-yet-failed states for a fraction of the query cost of deep diagnostic queries, which matters when the collector itself must not add meaningful load to a production writer.
- A monitoring pipeline that only reads CloudWatch misses everything database-internal: query-level hot spots, dead tuple ratios, and per-table sequential-scan trends are only visible from inside PostgreSQL, not from the instance/hypervisor level CloudWatch observes.

## 4. Possible Root Causes

- Not a failure workflow -- this is a reference/inventory of what to instrument, not a diagnosis of a specific problem.
- The most common gap this workflow closes: a monitoring pipeline built early in a cluster's life that only covers CPU/memory/connections (the CloudWatch-visible basics) and was never extended to cover vacuum health, XID age, or query-level statistics as the platform matured.

## 5. Investigation Strategy

1. Start with connection and session-level state (pg_stat_activity), since it is the highest-frequency, most immediately actionable signal.
2. Add per-database throughput and cache-efficiency counters (pg_stat_database), the cheapest broad health signal available.
3. Add table- and index-level activity (pg_stat_user_tables / pg_stat_user_indexes), which is where vacuum debt and lost access paths first become visible.
4. Add I/O and checkpoint activity (pg_stat_io, pg_stat_checkpointer, pg_stat_bgwriter), the PostgreSQL-side counterpart to CloudWatch's storage-layer metrics.
5. Add WAL generation, with the Aurora-specific caveat that pg_stat_wal itself cannot be queried on Aurora -- see script 05 and the Aurora notes below.
6. For each metric, decide the collection frequency (seconds for connections/activity, minutes for throughput/vacuum/WAL) before wiring it into a collector -- these views are cheap individually but querying all of them every few seconds across many databases adds up.

## 6. Prerequisites

- Role membership in pg_monitor (or pg_read_all_stats) for the monitoring role -- never grant broader privileges just to read statistics views.
- A place for the collected values to land (Prometheus via postgres_exporter, CloudWatch custom metrics, or a scheduled table as used by automation/growth-monitoring) -- this workflow defines *what* to collect, not the collector itself.
- Awareness that every view here is cumulative since stats_reset (or instantaneous for pg_stat_activity) -- rate/derivative calculation is the collector's job, not something a single query call reveals.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_connection_and_session_metrics.sql`](scripts/01_connection_and_session_metrics.sql) -- Snapshots current session state grouped by database/state/wait event, and connection utilization against max_connections.
2. [`scripts/02_database_throughput_and_cache_metrics.sql`](scripts/02_database_throughput_and_cache_metrics.sql) -- Per-database cumulative throughput, cache hit ratio, rollback ratio, deadlocks, and temp file counters.
3. [`scripts/03_table_and_index_activity_metrics.sql`](scripts/03_table_and_index_activity_metrics.sql) -- Dead tuple ratios and vacuum timestamps per table, plus index size and scan-activity inventory.
4. [`scripts/04_io_and_checkpoint_metrics.sql`](scripts/04_io_and_checkpoint_metrics.sql) -- Per-backend-type I/O statistics plus checkpointer and background-writer activity.
5. [`scripts/05_wal_generation_metrics.sql`](scripts/05_wal_generation_metrics.sql) -- Cluster-wide WAL generation statistics, with an Aurora-specific availability guard.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- pg_stat_wal is present in the catalog on Aurora PostgreSQL but cannot actually be queried: SELECTing it invokes pg_stat_get_wal(), which Aurora PostgreSQL (verified through 17.7) does not implement, raising 'function pg_stat_get_wal() does not exist'. Script 05 detects Aurora first (via a safe pg_proc-only check, never by calling an Aurora-only function directly) and reports CloudWatch VolumeWriteIOPs/WriteThroughput and the Performance Insights wait-event breakdown as the Aurora-native substitute.
- pg_stat_io on PostgreSQL/Aurora 17 has no read_bytes/write_bytes/extend_bytes columns (those were added only in PostgreSQL 18) -- every operation is reported as a count plus a fixed op_bytes, so byte volumes must be derived as reads/writes multiplied by op_bytes, which script 04 already does.
- Checkpoint counters live in pg_stat_checkpointer on PostgreSQL 17, not pg_stat_bgwriter (which is now limited to non-checkpoint buffer writes) -- monitoring pipelines built against pre-17 documentation commonly query the wrong view here.
- An Aurora failover resets every cumulative counter in this workflow on the promoted instance -- a monitoring pipeline that does not detect and annotate a failover event will show a false 'improvement' in every rate-based metric immediately afterward.

## 8. Interpretation Guide

- pg_stat_activity is the only view here that is a live snapshot rather than a cumulative counter -- everything else accumulates since stats_reset (typically instance start or the last Aurora failover) and must be diffed between two collection points to get a rate.
- A cache hit ratio (pg_stat_database) below roughly 99% on an OLTP exchange workload matters more on Aurora than on self-managed PostgreSQL, because a buffer miss becomes a round trip to the distributed storage layer rather than a local disk read.
- Dead tuple ratio and last_autovacuum together (pg_stat_user_tables) distinguish 'autovacuum is losing the race against write volume' from 'autovacuum is not reaching this table at all' -- the two require different fixes.
- A rising pct_forced_checkpoints (pg_stat_checkpointer) means checkpoint_timeout/max_wal_size tuning has fallen behind the current write rate -- this is one of the earliest SQL-visible signs of an I/O capacity problem, often before CloudWatch's storage-layer metrics move visibly.
- WAL generation cannot be read from pg_stat_wal on Aurora at all -- see script 05's guard and the Aurora notes below before building any alert on this view.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- This is an instrumentation workflow, not a remediation workflow -- any specific finding these metrics surface is remediated through its own dedicated category (vacuum-and-autovacuum, connections, tables-and-indexes, and so on).

**Short-term remediation** (hours to days):

- Wire any metric identified here as currently uncollected into the existing monitoring pipeline, prioritized by which gap would have shortened the most recent incident's time-to-detection.
- Set an initial alert threshold from this cluster's own observed baseline (see database-health/daily-health-check for how to establish one), not from a generic published number.

**Long-term engineering fix** (days to weeks):

- Formalize the collection cadence and retention for each metric family so the trend data survives long enough to support capacity planning, not just alerting on the current value.
- Feed the query-level and table-level metrics into the dashboard layout proposed in dashboard-recommendations so they are visible continuously, not only pulled on demand during an investigation.

## 10. Production Safety

- Every script in this workflow is strictly read-only: catalog and statistics views only, no DDL, no DML, and no session termination.
- Individually each script is inexpensive; running the full set on a tight interval (sub-second) across many databases is the only way this workload becomes noticeable -- size the collection frequency to the metric's actual rate of change (seconds for activity, minutes for the rest).
- Safe to run against a reader for the database/table/index/I/O metrics; run the connection and activity script against the writer if the writer's own session state is what needs monitoring, since pg_stat_activity is per-instance.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- This workflow does not itself define escalation thresholds -- each metric's escalation criteria lives in the workflow that owns that failure mode (see Related Issues).
- If auditing an existing pipeline surfaces a complete gap in an entire metric family (for example, no vacuum/XID visibility at all), treat closing that gap as urgent infrastructure work, not a backlog item -- it is the same gap that turns a slow-moving problem into a surprise incident.

## 12. Related Issues

- [performance-insights](../performance-insights/README.md)
- [cloudwatch](../cloudwatch/README.md)
- [dashboard-recommendations](../dashboard-recommendations/README.md)
- [comprehensive-health-check](../../database-health/comprehensive-health-check/README.md)
- [dead-tuples](../../vacuum-and-autovacuum/dead-tuples/README.md)
- [connection-exhaustion](../../connections/connection-exhaustion/README.md)
- [sequential-scan-investigation](../../tables-and-indexes/sequential-scan-investigation/README.md)
