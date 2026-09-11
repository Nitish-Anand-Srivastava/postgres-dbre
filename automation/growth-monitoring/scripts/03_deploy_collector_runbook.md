# 03_deploy_collector_runbook

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `03_deploy_collector_runbook.md` |
| Purpose | Documents the exact DDL for dba_toolkit.table_size_history and the periodic collector job that populates it -- deliberate, reviewed infrastructure you deploy once, not something to pipe into psql unread. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only (the query reads/writes state that only exists or is meaningful on the writer) |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | Varies by step -- read each step's own warning before executing it. |
| Required privileges | Table owner, or a role granted the `MAINTAIN` privilege on the table (PostgreSQL 16+), or a role with `pg_maintain` membership. DDL variants additionally require the privileges needed for the specific DDL statement (e.g. ownership to ALTER TABLE). |
| Prerequisites | Full read-only investigation for this workflow completed; maintenance window and second engineer approval obtained. |
| Execution order | Step 03 of workflow `automation/growth-monitoring` |
| Related scripts | 01_check_tracking_table_status.sql, ../../tables-and-indexes/rapidly-growing-tables/README.md, ../../storage-and-capacity/table-growth/README.md |

## How to interpret / use this runbook

This is infrastructure you deploy deliberately, not a script to run unread. Follow the numbered steps in order, adapt the schedule and retention window to your own operational cadence, and verify with scripts 01 and 02 afterward.

---

Read this runbook in full before running anything in it. It creates a new schema and table, and schedules a recurring job that writes to it. None of it runs automatically as part of this repository -- you are choosing to deploy this collector.

## 1. Create the schema and tracking table

```sql
CREATE SCHEMA IF NOT EXISTS dba_toolkit;

CREATE TABLE dba_toolkit.table_size_history (
    captured_at   timestamptz NOT NULL DEFAULT now(),
    schema_name   text        NOT NULL,
    table_name    text        NOT NULL,
    size_bytes    bigint      NOT NULL,
    PRIMARY KEY (captured_at, schema_name, table_name)
);

CREATE INDEX table_size_history_lookup
    ON dba_toolkit.table_size_history (schema_name, table_name, captured_at);
```

The column names (`captured_at`, `schema_name`, `table_name`, `size_bytes`) are exact and load-bearing: sql_blocks.table_growth_rate_from_snapshot() and every script in tables-and-indexes/rapidly-growing-tables and storage-and-capacity that reads this table expect these names precisely. Do not rename them.

## 2. The population query

This single INSERT is what a scheduled job runs on every collection interval. It records the current total size (heap plus indexes plus TOAST) of every ordinary and partitioned table in every non-system schema:

```sql
INSERT INTO dba_toolkit.table_size_history (captured_at, schema_name, table_name, size_bytes)
SELECT
    now(),
    n.nspname,
    c.relname,
    pg_total_relation_size(c.oid)
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p', 'm')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'dba_toolkit');
```

## 3. Schedule it -- Option A: pg_cron

See automation/health-checks for the full pg_cron enablement prerequisites (parameter group change plus a reboot, then a change-managed `CREATE EXTENSION pg_cron;`). Once available:

```sql
SELECT cron.schedule(
    'dba_toolkit_table_size_history_collector',
    '0 * * * *',
    $$INSERT INTO dba_toolkit.table_size_history (captured_at, schema_name, table_name, size_bytes)
      SELECT now(), n.nspname, c.relname, pg_total_relation_size(c.oid)
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
      WHERE c.relkind IN ('r', 'p', 'm')
        AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'dba_toolkit')$$
);
```

An hourly schedule (`0 * * * *`) is a reasonable default; a daily schedule (`0 2 * * *`) is sufficient for most capacity-planning purposes and produces a much smaller table over time -- pick the cadence that matches how quickly the growth questions you ask actually need to be answered.

## 3. Schedule it -- Option B: external scheduler

If pg_cron is not enabled on this cluster, run the same population query from an EventBridge-scheduled Lambda function or a scheduled ECS/Fargate task connecting to the writer endpoint, using the same read/write role that owns the `dba_toolkit` schema. No additional privilege beyond `INSERT` on this one table is required.

## 4. Retention -- prune the history table itself

The collector table will itself grow forever without a retention policy. Add a second scheduled step (via the same pg_cron job or a second one, or the equivalent step in an external scheduler) to prune old rows on a documented retention window, for example:

```sql
DELETE FROM dba_toolkit.table_size_history
WHERE captured_at < now() - interval '13 months';
```

Thirteen months keeps a full year of history available for year-over-year growth comparisons even a month after the retention boundary passes; adjust to your own capacity-review cadence.

## 5. Confirm it is working

Run script 01 in this workflow immediately after deployment to confirm the table exists, and again after at least two collection intervals have elapsed to confirm rows are actually accumulating. Run script 02 after at least a week to confirm the collection cadence is healthy.
