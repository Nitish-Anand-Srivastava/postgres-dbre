# CloudWatch Metrics for Aurora PostgreSQL

**Category:** Observability | **Workflow:** `observability/cloudwatch`

## 1. Problem Description

The Aurora-published CloudWatch metrics an on-call DBA and platform team should already have alarms on, and -- for each one -- the SQL-level query in this repository that explains *why* the metric moved. CloudWatch metrics come from the instance/hypervisor and Aurora storage layer, not from inside PostgreSQL, so they answer 'something changed' reliably but rarely 'what changed inside the database'; this workflow is the bridge between the two.

## 2. Typical Symptoms

- A CloudWatch alarm has fired (CPUUtilization, DatabaseConnections, FreeableMemory, DiskQueueDepth, or similar) and the database-level cause is not yet known.
- A capacity or cost review is looking at VolumeBytesUsed or connection trend lines and wants the SQL-level explanation behind the trend.
- A new cluster is being onboarded and the team needs to know which CloudWatch metrics to alarm on in the first place.

## 3. Business Impact

- CloudWatch alarms are almost always the first signal an on-call engineer sees, often before any application-level alert -- knowing immediately which SQL script corresponds to a given metric turns 'an alarm fired' into 'here is what is happening inside the database' in the first minute of an incident, not the tenth.
- AuroraReplicaLag and BufferCacheHitRatio moving in the wrong direction are both directly user-visible on an exchange (stale reads, degraded latency) well before CPUUtilization or DatabaseConnections would suggest a problem, so alarming on the right metrics matters as much as alarming on the obvious ones.
- VolumeBytesUsed is a direct, ongoing infrastructure cost on Aurora (storage billed on the shared cluster volume, never reclaimed automatically) -- connecting its trend line back to the specific tables or WAL retention driving it turns a cost conversation into an actionable engineering ticket.

## 4. Possible Root Causes

- Not a failure workflow -- this maps monitoring signals to their SQL-level explanation rather than diagnosing a specific failure.
- The most common gap this workflow closes: a team alarming only on CPUUtilization and DatabaseConnections while ignoring AuroraReplicaLag, BufferCacheHitRatio, or DiskQueueDepth, all of which degrade user experience on an exchange well before CPU or connection count would.

## 5. Investigation Strategy

1. Identify which specific CloudWatch metric triggered the investigation and its exact time window.
2. Run the SQL-side capacity and load snapshot for the current values of the metrics that have a direct database-internal counterpart.
3. For AuroraReplicaLag specifically, run the Aurora-native replica status query rather than assuming pg_stat_replication will show anything (it does not, for Aurora readers).
4. Use the metric-to-SQL mapping reference to identify which workflow in this repository owns deeper investigation of the specific metric that moved.
5. For a metric with no direct SQL-level counterpart (CPUUtilization, FreeableMemory), correlate its timing against the DB-side signals available (query volume, cache hit ratio, checkpoint activity) rather than expecting a single query to explain it.

## 6. Prerequisites

- CloudWatch console/API access scoped to the RDS/Aurora namespace for the account and region.
- Role membership in pg_monitor (or pg_read_all_stats) for the SQL-side scripts.
- Alarms already configured, or this workflow's mapping table used as the starting checklist for configuring them.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_sql_side_capacity_and_load_snapshot.sql`](scripts/01_sql_side_capacity_and_load_snapshot.sql) -- One-row snapshot of the SQL-visible counterparts to the most commonly alarmed-on Aurora CloudWatch metrics.
2. [`scripts/02_replication_lag_sql_companion.sql`](scripts/02_replication_lag_sql_companion.sql) -- Aurora-native cluster-wide replica status and lag, the SQL-side companion to the AuroraReplicaLag CloudWatch metric.
3. [`scripts/03_cloudwatch_metric_to_sql_mapping.md`](scripts/03_cloudwatch_metric_to_sql_mapping.md) -- Reference table mapping key Aurora CloudWatch metrics to their SQL-level companion query and recommended alarm guidance.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- AuroraReplicaLag has no meaning on a standalone/single-instance cluster and reports per-reader on a multi-instance Aurora cluster -- it is not the same metric as, and should not be confused with, standard PostgreSQL streaming replication lag on a self-managed replica.
- VolumeBytesUsed reflects Aurora's shared cluster storage volume, which grows in 10GiB increments and is never reduced by deleting rows or dropping objects -- do not expect it to track pg_database_size() precisely, and do not expect it to shrink after an archival/purge operation the way logical size will.
- CPUUtilization and FreeableMemory on Aurora are reported per-instance (writer and each reader separately) -- when correlating against a SQL-side query, make sure the SQL session and the CloudWatch graph are pointed at the same specific instance, not merely 'the cluster'.
- Aurora storage I/O (VolumeReadIOPs/VolumeWriteIOPs) is billed and capacity-planned separately from compute; a CPUUtilization metric that looks comfortable does not mean I/O capacity is comfortable too -- check both independently.

## 8. Interpretation Guide

- CloudWatch metrics are authoritative for anything infrastructure- or billing-level (actual CPUUtilization, actual billed VolumeBytesUsed); the SQL-side queries in this workflow are a proxy that explains the *database-visible* contributor, and the two will not always match exactly (for example, VolumeBytesUsed includes storage Aurora has allocated but not yet reported back to pg_database_size()).
- DatabaseConnections (CloudWatch) and current_connections (SQL) should track closely; a persistent gap between them usually means connections from a source CloudWatch is not correctly attributing (rare) or a metric collection delay, not a real discrepancy.
- BufferCacheHitRatio (CloudWatch) and cache_hit_pct_all_databases (SQL, script 01) measure the same underlying phenomenon at slightly different granularity (instance-wide vs. per-database) -- expect them to move together, not to match to the decimal.
- AuroraReplicaLag (CloudWatch, per-reader) and the lag reported by aurora_replica_status() (SQL, script 02) are the same underlying Aurora storage-layer replication mechanism -- use the SQL version when you need to query from any instance in the cluster without switching AWS console context.
- DiskQueueDepth and VolumeReadIOPs/VolumeWriteIOPs have no single equivalent SQL counter; pg_stat_checkpointer's pct_forced_checkpoints and pg_stat_io's read/write counts are the closest SQL-visible proxies and are directional, not a byte-for-byte match.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- This workflow is diagnostic/mapping, not remedial -- once the SQL-side counterpart identifies the responsible internal behavior, route to the dedicated workflow that owns it (see the mapping reference and Related Issues).

**Short-term remediation** (hours to days):

- Add any alarm identified as missing from the mapping reference (script 03) to this cluster's CloudWatch alarm configuration, using this cluster's own observed baseline for the threshold rather than a generic published number.
- For a metric with an established SQL-level companion query, add that query's output to the incident ticket alongside the CloudWatch graph so the review has both the infrastructure and database-internal view together.

**Long-term engineering fix** (days to weeks):

- Build the recommended alarm set from the mapping reference into infrastructure-as-code so every new cluster starts with the full set rather than only the metrics someone remembered to configure.
- Feed both the CloudWatch metrics and their SQL-side companions into the dashboard layout proposed in dashboard-recommendations so the two are viewed side by side routinely, not only reconstructed during an incident.

## 10. Production Safety

- Reading CloudWatch metrics imposes no load on the database at all -- it is a separate AWS service reading instance/hypervisor and storage-layer telemetry.
- Every SQL script in this workflow is strictly read-only and safe to run at any time, including during an active incident.
- Creating or modifying a CloudWatch alarm (described in script 03's reference material) is an AWS-side configuration action with no database impact, but should still go through normal change review since it affects on-call paging behavior.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- AuroraReplicaLag sustained above the application's read-your-own-write tolerance -- escalate to replication-and-ha/reader-lag-investigation.
- BufferCacheHitRatio trending down over successive days with no corresponding traffic explanation -- escalate to performance/high-iops or database-health/capacity-health-check.
- DatabaseConnections approaching max_connections with the SQL-side connections/max-connections-planning headroom check confirming the same -- escalate immediately, this is a hard ceiling with no graceful degradation.
- VolumeBytesUsed growing faster than the documented business growth rate with no SQL-side table growth explaining the difference -- escalate to storage-and-capacity/unexpected-storage-growth to check for retained WAL or an orphaned replication slot.

## 12. Related Issues

- [postgres-metrics](../postgres-metrics/README.md)
- [performance-insights](../performance-insights/README.md)
- [dashboard-recommendations](../dashboard-recommendations/README.md)
- [replication-lag](../../replication-and-ha/replication-lag/README.md)
- [max-connections-planning](../../connections/max-connections-planning/README.md)
- [database-growth](../../storage-and-capacity/database-growth/README.md)
