# 04_scheduling_runbook

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `04_scheduling_runbook.md` |
| Purpose | Documents how to schedule the capacity snapshot scripts with threshold-based alerting, via an external scheduler (preferred, since it can alert directly) or pg_cron plus a separate poller. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only (the query reads/writes state that only exists or is meaningful on the writer) |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | Varies by step -- read each step's own warning before executing it. |
| Required privileges | Table owner, or a role granted the `MAINTAIN` privilege on the table (PostgreSQL 16+), or a role with `pg_maintain` membership. DDL variants additionally require the privileges needed for the specific DDL statement (e.g. ownership to ALTER TABLE). |
| Prerequisites | Full read-only investigation for this workflow completed; maintenance window and second engineer approval obtained. |
| Execution order | Step 04 of workflow `automation/capacity-monitoring` |
| Related scripts | ../health-checks/README.md, ../../storage-and-capacity/capacity-forecasting/README.md, ../../database-health/capacity-health-check/README.md |

## How to interpret / use this runbook

This is a documentation runbook, not an executable script -- adapt the illustrative thresholds and alerting destination to your own instance class, workload, and existing alerting stack before applying it.

---

## Why an external scheduler is usually preferred here

Unlike growth-monitoring or xid-monitoring, capacity thresholds (connection utilization, storage growth rate, I/O pressure) typically need to reach an alerting system directly and quickly. `pg_cron` can only write SQL results back into the database -- it cannot call CloudWatch, PagerDuty, or Slack itself. An external scheduler that can call those systems directly is usually the simpler design for this specific workflow.

## Option A: external scheduler with direct alerting (recommended)

An AWS Lambda function on an Amazon EventBridge (CloudWatch Events) scheduled rule:

1. Connects to the writer endpoint (directly, or via the RDS Data API) using the standard read-only `pg_monitor` role.
2. Runs the snapshot scripts in this workflow.
3. Publishes the key figures (`pct_utilized`, database size deltas, `pct_forced_checkpoints`) as CloudWatch custom metrics.
4. Relies on standard CloudWatch alarms on those custom metrics for paging -- this reuses your existing alerting infrastructure rather than building a new one.

Recommended starting thresholds (adjust to your own instance class and workload): connection utilization above 80% sustained for more than one consecutive scheduled run; a single-review storage size increase materially outside the documented business growth rate; `pct_forced_checkpoints` above roughly 10% sustained across several consecutive runs.

## Option B: pg_cron plus a separate poller

If pg_cron is already enabled and preferred, schedule the snapshot queries to log into a `dba_toolkit.capacity_snapshot_history` table (following the same pattern as `dba_toolkit.table_size_history` in automation/growth-monitoring), and have a separate lightweight external poller (a small scheduled Lambda, or your existing metrics-scraping agent) read that table and apply the alerting thresholds. This still requires an external component to actually page anyone -- pg_cron alone cannot close that gap.

## Recommended cadence

Every 15-60 minutes for connection utilization (it can change quickly during a volatility spike); daily is sufficient for the storage growth-rate and I/O-pressure signals, which develop more slowly.
