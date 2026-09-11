# 04_scheduling_runbook

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `04_scheduling_runbook.md` |
| Purpose | Documents how to schedule the database-health/ workflows on a recurring basis, via pg_cron where it is enabled or an external scheduler where it is not. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only (the query reads/writes state that only exists or is meaningful on the writer) |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | Varies by step -- read each step's own warning before executing it. |
| Required privileges | Table owner, or a role granted the `MAINTAIN` privilege on the table (PostgreSQL 16+), or a role with `pg_maintain` membership. DDL variants additionally require the privileges needed for the specific DDL statement (e.g. ownership to ALTER TABLE). |
| Prerequisites | Full read-only investigation for this workflow completed; maintenance window and second engineer approval obtained. |
| Execution order | Step 04 of workflow `automation/health-checks` |
| Related scripts | ../growth-monitoring/README.md, ../../database-health/daily-health-check/README.md |

## How to interpret / use this runbook

This is a documentation runbook, not an executable script -- read the option that matches whether pg_cron is enabled on this cluster, adapt the illustrative SQL/Lambda outline to your actual health-check queries and alerting destination, and apply it deliberately rather than piping any part of this file into psql as-is.

---

## Option A: pg_cron (requires it to already be enabled)

`pg_cron` runs scheduled jobs *inside* the database server process, on the database server's clock, as the role that scheduled the job. It cannot execute host-level commands or reach external systems (Slack, PagerDuty, CloudWatch) directly -- it can only run SQL. This makes it a good fit for checks whose output is fine to leave in a results-log table for a human or a separate poller to review, and a poor fit for anything that must page someone directly.

**Enabling pg_cron (a one-time, change-managed prerequisite, not something this workflow does for you):**

1. Add `pg_cron` to `shared_preload_libraries` on the Aurora DB cluster parameter group. This requires an instance reboot to take effect -- schedule it through your normal change-management process, the same as any other parameter group change that needs a reboot.
2. After the reboot, have an administrator run `CREATE EXTENSION pg_cron;` once, in a change-managed session, in the database designated to host the `cron` schema (Aurora typically requires this to be the `postgres` database; jobs can still target other databases on the same cluster via the `database` argument to `cron.schedule()`).
3. Confirm it is available with script 01 in this workflow before scheduling anything.

**Scheduling a health check once pg_cron is available:**

```sql
-- Runs daily-health-check's read-only scripts every morning at 06:00 UTC and
-- logs a simple completion marker. In practice you would adapt this to invoke
-- your actual daily-health-check queries (or a wrapper function you have written
-- that runs them and stores structured results) rather than a bare marker insert.
SELECT cron.schedule(
    'daily_health_check',
    '0 6 * * *',
    $$INSERT INTO dba_toolkit.health_check_log (checked_at, workflow) VALUES (now(), 'daily-health-check')$$
);
```

Review the job afterward with script 01 (is it registered) and script 02 (is it actually succeeding) in this workflow -- a scheduled job that silently fails every run is worse than no schedule at all.

To remove a job later: `SELECT cron.unschedule('daily_health_check');`

## Option B: external scheduler (no pg_cron dependency)

When `pg_cron` is not enabled, or when a check's result needs to reach an external alerting system directly, schedule it outside the database instead:

- An AWS Lambda function on an Amazon EventBridge (CloudWatch Events) scheduled rule, connecting to the writer endpoint (directly, or via the RDS Data API for a Data-API-enabled Aurora Serverless cluster) to run the health-check queries and publish a CloudWatch custom metric or post to an existing alerting channel on failure.
- A scheduled ECS Fargate task or a CI/CD scheduled pipeline running `psql` against the cluster with a read-only monitoring role, piping output to your existing log aggregation and alerting stack.

Either external option needs the exact same read-only database role (`pg_monitor` membership, `CONNECT` on the target database) that every script in this repository already documents -- no additional database privilege is required to schedule a check externally.

## Which database-health workflows to schedule, and how often

- `daily-health-check`: daily, off-peak, e.g. early morning UTC.
- `comprehensive-health-check` and `capacity-health-check`: weekly or monthly -- they are heavier and intended for a periodic deep review, not a daily loop.
- `pre-deployment-check` / `post-deployment-check` and `pre-maintenance-check` / `post-maintenance-check`: triggered by the deployment/maintenance pipeline itself, not a fixed schedule -- wire them into the pipeline rather than a cron expression.
