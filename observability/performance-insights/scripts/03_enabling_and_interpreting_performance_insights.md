# 03_enabling_and_interpreting_performance_insights

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `03_enabling_and_interpreting_performance_insights.md` |
| Purpose | Runbook for confirming/enabling Performance Insights on a DB instance and reading its DB load view correctly during an investigation. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Any instance (writer or reader) |
| Safety | LOW RISK WRITE (AWS instance configuration change to enable Performance Insights; no SQL statements executed against the database) |
| Expected impact | None -- this is reference/planning documentation, not an executable script. Any AWS-side action it describes (enabling a feature, creating an alarm) is called out explicitly and is a change-managed action outside this repository's SQL scope. |
| Required privileges | IAM permission to describe/modify the DB instance and to view Performance Insights (pi:GetResourceMetrics, pi:DescribeDimensionKeys, rds:ModifyDBInstance) for the enable step; no PostgreSQL role required for the console/API portions. |
| Prerequisites | None to read this runbook. Enabling Performance Insights on an existing instance should be scheduled like any other instance-modifying change. |
| Execution order | Step 03 of workflow `observability/performance-insights` |
| Related scripts | ../wait-event-analysis/README.md, ../../performance/high-database-load/README.md |

## How to interpret / use this runbook

Follow the numbered steps in order during a live investigation. The enable/modify step is the only part of this runbook that changes anything -- everything else is read-only console/API usage.

---

## Checking whether Performance Insights is enabled

Performance Insights is a property of the DB *instance* (not the cluster),
configured through the AWS Console, CLI, or infrastructure-as-code -- it is
not something a SQL script can query from inside PostgreSQL. Check via the
CLI:

```
aws rds describe-db-instances \
  --db-instance-identifier <instance-identifier> \
  --query 'DBInstances[0].PerformanceInsightsEnabled'
```

## Enabling it on an existing instance

Enabling Performance Insights on an instance that does not already have it
is a change-managed infrastructure action, not a database statement, and is
therefore described here rather than shipped as SQL:

```
aws rds modify-db-instance \
  --db-instance-identifier <instance-identifier> \
  --enable-performance-insights \
  --performance-insights-retention-period 7 \
  --apply-immediately
```

Review before running: on some older instance classes this can require a
brief instance modification window; test on a non-writer instance first if
this cluster has never had it enabled, and avoid `--apply-immediately`
during peak trading hours on the writer if the change can instead wait for
the next scheduled maintenance window.

## Reading the DB load view

1. Open the instance's Performance Insights dashboard and select the
   incident's time range.
2. Read the DB load line against the instance's vCPU count (shown as a
   reference line) before anything else -- load below vCPU count usually
   means available parallelism, not contention.
3. Switch the breakdown dimension to "Wait event" first to classify the
   load (CPU / Lock / IO / IPC / other), then to "SQL" to identify the
   responsible statement(s) within the dominant wait event.
4. Cross-reference the queryid shown against script 02 (if the load is
   current) or pg_stat_statements directly (if pg_stat_statements has not
   been reset since the incident) for the full statement text and stats.

## When PI alone is not enough

Performance Insights aggregates; it does not show individual session
identity, client address, or the exact current query text of a specific
backend. For that level of detail on a currently ongoing issue, use the
live per-session scripts in wait-event-analysis and
concurrency-and-locking/blocked-queries alongside PI's historical view.
