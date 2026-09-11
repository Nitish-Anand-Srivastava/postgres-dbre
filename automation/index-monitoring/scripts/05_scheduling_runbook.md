# 05_scheduling_runbook

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `05_scheduling_runbook.md` |
| Purpose | Documents how to run the index-health snapshot scripts on a recurring schedule via pg_cron or an external scheduler. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only (the query reads/writes state that only exists or is meaningful on the writer) |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | Varies by step -- read each step's own warning before executing it. |
| Required privileges | Table owner, or a role granted the `MAINTAIN` privilege on the table (PostgreSQL 16+), or a role with `pg_maintain` membership. DDL variants additionally require the privileges needed for the specific DDL statement (e.g. ownership to ALTER TABLE). |
| Prerequisites | Full read-only investigation for this workflow completed; maintenance window and second engineer approval obtained. |
| Execution order | Step 05 of workflow `automation/index-monitoring` |
| Related scripts | ../growth-monitoring/README.md, ../../tables-and-indexes/unused-indexes/README.md |

## How to interpret / use this runbook

This is a documentation runbook, not an executable script -- adapt the illustrative DDL/scheduling SQL to your own cadence and storage destination before applying it.

---

## Recommended cadence

Weekly or monthly is typically sufficient -- index usage and growth trends develop over weeks, not hours, so there is little value in a tighter cadence than for storage-and-capacity's other scheduled checks.

## Option A: pg_cron

See automation/health-checks for the full pg_cron enablement prerequisites. Once available, record results into a history table rather than only reading the live value, so a trend is visible:

```sql
CREATE TABLE IF NOT EXISTS dba_toolkit.index_health_history (
    captured_at    timestamptz NOT NULL DEFAULT now(),
    schema_name    text        NOT NULL,
    table_name     text        NOT NULL,
    index_name     text        NOT NULL,
    index_size_bytes bigint    NOT NULL,
    idx_scan       bigint,
    is_valid       boolean     NOT NULL,
    PRIMARY KEY (captured_at, schema_name, index_name)
);

SELECT cron.schedule(
    'dba_toolkit_index_health_collector',
    '0 3 * * 0',
    $$INSERT INTO dba_toolkit.index_health_history
          (captured_at, schema_name, table_name, index_name, index_size_bytes, idx_scan, is_valid)
      SELECT
          now(), n.nspname, c.relname, i.relname,
          pg_relation_size(i.oid), s.idx_scan, ix.indisvalid
      FROM pg_index ix
      JOIN pg_class c ON c.oid = ix.indrelid
      JOIN pg_class i ON i.oid = ix.indexrelid
      JOIN pg_namespace n ON n.oid = c.relnamespace
      JOIN pg_stat_all_indexes s ON s.indexrelid = ix.indexrelid
      WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')$$
);
```

The example above runs weekly (Sundays at 03:00 UTC, `0 3 * * 0`). Adjust to your own review cadence.

## Option B: external scheduler

Where pg_cron is not enabled, run the same population query from an EventBridge-scheduled Lambda or a scheduled task using the standard read-only `pg_monitor` role, writing results to your existing metrics store instead of a database table if preferred.

## Retention

Prune old rows on a documented retention window, following the same pattern as `dba_toolkit.table_size_history` in automation/growth-monitoring.
