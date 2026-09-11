# 03_scheduling_runbook

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `03_scheduling_runbook.md` |
| Purpose | Documents how to run the XID age snapshot scripts on a recurring schedule, with a recommended alert threshold, via pg_cron or an external scheduler. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only (the query reads/writes state that only exists or is meaningful on the writer) |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | Varies by step -- read each step's own warning before executing it. |
| Required privileges | Table owner, or a role granted the `MAINTAIN` privilege on the table (PostgreSQL 16+), or a role with `pg_maintain` membership. DDL variants additionally require the privileges needed for the specific DDL statement (e.g. ownership to ALTER TABLE). |
| Prerequisites | Full read-only investigation for this workflow completed; maintenance window and second engineer approval obtained. |
| Execution order | Step 03 of workflow `automation/xid-monitoring` |
| Related scripts | ../growth-monitoring/README.md, ../../transactions-and-xid/transaction-age/README.md |

## How to interpret / use this runbook

This is a documentation runbook, not an executable script -- adapt the illustrative DDL/scheduling SQL to your own threshold and alerting destination before applying it.

---

## Recommended cadence and threshold

Run both age-snapshot scripts at least daily; hourly is reasonable on a very high-write cluster where age can climb quickly. Alert at 40-50% of `autovacuum_freeze_max_age` -- this leaves weeks of lead time before the 75% threshold that transactions-and-xid/transaction-age treats as an escalation trigger, and far more before the emergency failsafe.

## Option A: pg_cron

See automation/health-checks for the full pg_cron enablement prerequisites. Once available, schedule a wrapper that records the result into a small history table rather than only ever reading the live value, so a trend is visible:

```sql
CREATE TABLE IF NOT EXISTS dba_toolkit.xid_age_history (
    captured_at              timestamptz NOT NULL DEFAULT now(),
    datname                  text        NOT NULL,
    xid_age                  bigint      NOT NULL,
    pct_of_freeze_max_age    numeric     NOT NULL,
    PRIMARY KEY (captured_at, datname)
);

SELECT cron.schedule(
    'dba_toolkit_xid_age_collector',
    '0 * * * *',
    $$INSERT INTO dba_toolkit.xid_age_history (captured_at, datname, xid_age, pct_of_freeze_max_age)
      SELECT
          now(),
          datname,
          age(datfrozenxid),
          round(100.0 * age(datfrozenxid) /
              (SELECT setting::numeric FROM pg_settings WHERE name = 'autovacuum_freeze_max_age'), 2)
      FROM pg_database
      WHERE datallowconn$$
);
```

Add a threshold check as a second scheduled job (or an external alerting rule reading this table) that fires when `pct_of_freeze_max_age` exceeds your chosen threshold for any row.

## Option B: external scheduler

Where pg_cron is not enabled, run the same two age-snapshot queries from an EventBridge-scheduled Lambda or a scheduled task using the standard read-only `pg_monitor` role, and publish `pct_of_freeze_max_age` as a CloudWatch custom metric with an alarm at your chosen threshold -- this is often preferable here specifically because it lets the alarm page directly, without needing a separate poller on the `dba_toolkit.xid_age_history` table.

## Retention

Prune `dba_toolkit.xid_age_history` on the same kind of documented retention window as `dba_toolkit.table_size_history` in automation/growth-monitoring (a year or so is typically more than enough for this narrow, low-cardinality table).
