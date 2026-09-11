# 02_baseline_dashboard_layout_recommendations

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `02_baseline_dashboard_layout_recommendations.md` |
| Purpose | Proposed baseline panel layout for a Grafana/CloudWatch Aurora PostgreSQL DBA dashboard, grouped by operational question. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Any instance (writer or reader) |
| Safety | READ ONLY (reference/planning documentation only; no SQL statements are executed by this file) |
| Expected impact | None -- this is reference/planning documentation, not an executable script. Any AWS-side action it describes (enabling a feature, creating an alarm) is called out explicitly and is a change-managed action outside this repository's SQL scope. |
| Required privileges | Role membership in `pg_monitor` (or `pg_read_all_stats`) is sufficient. No superuser required. |
| Prerequisites | None to read this reference. Each panel's underlying script/metric has its own prerequisites. |
| Execution order | Step 02 of workflow `observability/dashboard-recommendations` |
| Related scripts | 01_single_row_dashboard_snapshot.sql |

## How to interpret / use this runbook

Use this as the starting checklist when building a new dashboard or auditing an existing one -- each row names the exact script/metric in this repository (or CloudWatch) that backs it, so implementation is a direct lookup rather than a design exercise.

---

## Recommended panel groups

Organize the dashboard by operational question, not by data source. For
each group below, the "Source" column names the workflow/script in this
repository (or the CloudWatch metric) that backs it.

### 1. Connections & load

| Panel | Source |
| --- | --- |
| Current connections vs. `max_connections` (gauge) | `postgres-metrics` script 01, or CloudWatch `DatabaseConnections` |
| Connections by application/user (table) | `postgres-metrics` script 01 (`connections_by_application_and_user`-style query) |
| Wait event distribution (stacked time series) | `wait-event-analysis` script 01, or Performance Insights DB load |
| Longest open transaction (stat) | This workflow's script 01, or `database-health/daily-health-check` |

### 2. Replication & lag

| Panel | Source |
| --- | --- |
| Aurora reader lag per reader (time series) | `cloudwatch` script 02 (`aurora_replica_status()`), or CloudWatch `AuroraReplicaLag` |
| Replication slot WAL retention (table) | `database-health/capacity-health-check` script 05 |

### 3. Vacuum & XID age

| Panel | Source |
| --- | --- |
| Worst `pct_of_freeze_max_age` across databases (gauge, alert threshold) | This workflow's script 01, or `database-health/daily-health-check` |
| Dead tuple ratio, top tables (table) | `postgres-metrics` script 03 |
| Active autovacuum workers (table) | `database-health/comprehensive-health-check` script 08 |

### 4. Query performance

| Panel | Source |
| --- | --- |
| Top statements by total time (table, refreshed periodically) | `slow-query-observability` script 01 |
| Top statements by mean time (table) | `slow-query-observability` script 02 |
| DB load by SQL (Performance Insights embed or equivalent) | `performance-insights` script 02 |

### 5. I/O & checkpoints

| Panel | Source |
| --- | --- |
| Checkpoint pct forced vs. scheduled (time series) | `postgres-metrics` script 04, or CloudWatch `DiskQueueDepth` |
| pg_stat_io read/write volume by backend type (table) | `postgres-metrics` script 04 |
| CloudWatch Volume IOPS (time series) | CloudWatch `VolumeReadIOPs` / `VolumeWriteIOPs` |

### 6. Storage & capacity

| Panel | Source |
| --- | --- |
| Database and largest-table sizes (table) | `database-health/capacity-health-check` script 01 |
| CloudWatch storage volume trend (time series) | CloudWatch `VolumeBytesUsed` |
| Temp file volume (time series) | `postgres-metrics` script 02, or `database-health/capacity-health-check` script 06 |

## Implementation notes

* Prefer a single shared dashboard definition (Grafana provisioning-as-code,
  or a shared CloudWatch dashboard template) applied across every cluster
  in the fleet, rather than one dashboard per cluster maintained by hand.
* Annotate the dashboard with Aurora failover events so a reset in
  cumulative counters is visually explained rather than misread as an
  improvement.
* Start every new cluster with this baseline layout before it goes to
  production, rather than treating dashboarding as a follow-up task after
  the first incident.
