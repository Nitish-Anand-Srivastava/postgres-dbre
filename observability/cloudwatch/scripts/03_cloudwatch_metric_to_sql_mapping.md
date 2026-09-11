# 03_cloudwatch_metric_to_sql_mapping

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `03_cloudwatch_metric_to_sql_mapping.md` |
| Purpose | Reference table mapping key Aurora CloudWatch metrics to their SQL-level companion query and recommended alarm guidance. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Any instance (writer or reader) |
| Safety | READ ONLY (reference documentation only; no SQL statements are executed by this file) |
| Expected impact | None -- this is reference/planning documentation, not an executable script. Any AWS-side action it describes (enabling a feature, creating an alarm) is called out explicitly and is a change-managed action outside this repository's SQL scope. |
| Required privileges | Role membership in `pg_monitor` (or `pg_read_all_stats`) is sufficient. No superuser required. |
| Prerequisites | None to read this reference. The scripts it links to have their own prerequisites. |
| Execution order | Step 03 of workflow `observability/cloudwatch` |
| Related scripts | 01_sql_side_capacity_and_load_snapshot.sql, 02_replication_lag_sql_companion.sql |

## How to interpret / use this runbook

Use the table to go from 'this CloudWatch alarm fired' to 'this is the SQL script that explains it' in one lookup, without needing to remember the mapping from memory during an incident.

---

## Metric-to-SQL mapping

| CloudWatch metric | SQL-level companion | Notes |
| --- | --- | --- |
| `CPUUtilization` | No direct SQL counterpart; correlate with query volume/type via slow-query-observability | Sustained high CPU with low active-session count suggests a few CPU-heavy statements; use performance-insights to identify them. |
| `DatabaseConnections` | `pct_connections_used` (script 01) | Should track closely; alarm at ~80% of `max_connections` as an early warning, not only at exhaustion. |
| `FreeableMemory` | No direct SQL counterpart; correlate with `work_mem`/`shared_buffers` settings and temp file growth (script 01, `total_temp_bytes_since_reset`) | A shrinking trend alongside rising temp file volume suggests memory pressure from oversized sort/hash operations. |
| `VolumeBytesUsed` | `total_logical_database_size` (script 01), plus `database-health/capacity-health-check` for the full breakdown | Aurora storage never shrinks automatically; a rising trend with no matching logical size growth suggests retained WAL (replication slots) rather than table growth. |
| `VolumeReadIOPs` / `VolumeWriteIOPs` | `pg_stat_io` counts, `pct_forced_checkpoints` (script 01) | No exact SQL equivalent; both are directional proxies for I/O pressure at the storage layer. |
| `AuroraReplicaLag` | `aurora_replica_status()` (script 02) | Per-reader metric; always use the Aurora-native function, never `pg_stat_replication`, for Aurora readers. |
| `BufferCacheHitRatio` | `cache_hit_pct_all_databases` (script 01) | Instance-wide vs. per-database granularity; expect close tracking, not exact equality. |
| `DiskQueueDepth` | `pct_forced_checkpoints`, `pg_stat_io` read/write counts (script 01, postgres-metrics script 04) | No exact SQL equivalent; treat as directional. |

## Recommended baseline alarm set

At minimum, alarm on: `DatabaseConnections` (approaching `max_connections`),
`FreeableMemory` (approaching zero), `VolumeBytesUsed` (unexpected growth
rate), `AuroraReplicaLag` (above the application's read-your-own-write
tolerance), and `CPUUtilization` (sustained high). Configuring or updating
these alarms is an AWS-side action (console, CLI, or infrastructure-as-code)
and should go through the same change review as any other alerting change,
since it affects on-call paging behavior.

## How to use this table during an incident

1. Identify which CloudWatch metric triggered the alert and its exact time
   window.
2. Find its row in the mapping table above and run the referenced SQL
   script for the current, SQL-visible picture.
3. If the metric has no direct SQL companion, use the "Notes" column's
   correlation guidance rather than searching for a query that does not
   exist.
4. Route the finding to the dedicated workflow in this repository that
   owns the underlying database behavior, using this table as the index.
