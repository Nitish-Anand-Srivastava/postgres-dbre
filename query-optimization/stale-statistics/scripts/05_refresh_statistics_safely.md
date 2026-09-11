# 05_refresh_statistics_safely

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `05_refresh_statistics_safely.md` |
| Purpose | Guarded runbook for refreshing planner statistics on specific tables with ANALYZE. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only -- readers are in continuous recovery and cannot update catalog statistics. |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | ANALYZE takes a SHARE UPDATE EXCLUSIVE lock (does not block reads or writes) and reads a sample of the table, which is real storage I/O on a very large table. ALTER TABLE ... SET takes a brief ACCESS EXCLUSIVE lock. |
| Required privileges | Table ownership, the MAINTAIN privilege (PostgreSQL 16+), or pg_maintain membership to run ANALYZE. Table ownership to change per-table storage options. |
| Prerequisites | Scripts 01-04 completed and the specific stale tables identified. Change record raised for a production exchange cluster. |
| Execution order | Step 05 of workflow `query-optimization/stale-statistics` |
| Related scripts | ../cardinality-estimation/README.md, ../../vacuum-and-autovacuum/analyze-statistics/README.md |

## How to interpret / use this runbook

Use this immediately after any migration or bulk data change, and whenever script 01 shows a latency-sensitive table above roughly 20% drift. The verification in step 2 is not optional: an ANALYZE that ran against the wrong database or was cut short by an inherited statement_timeout looks exactly like one that succeeded until you check last_analyze.

---

## Why ANALYZE is not a .sql script in this toolkit

`ANALYZE` is a maintenance command that writes catalog data and takes a lock on the
target table. Which tables to analyze, and when, is an operational decision that
depends on table size, current load, and what else is running. An investigation
script must never make that decision on the operator's behalf, and it must never
execute a statement that a read-only session could not run. Hence: a runbook.

## What ANALYZE actually costs

- **Lock:** `SHARE UPDATE EXCLUSIVE`. It does **not** block `SELECT`, `INSERT`,
  `UPDATE`, or `DELETE`. It **does** conflict with a concurrent `VACUUM`, another
  `ANALYZE`, and most `ALTER TABLE` forms on the same table.
- **I/O:** reads a random sample of pages, sized from the statistics target
  (roughly 300 x target pages per column). Seconds on a small table; minutes and
  real storage I/O on a multi-hundred-gigabyte table.
- **Data:** never rewrites table data. There is nothing to roll back and no
  possibility of data loss.
- **Effect:** immediate. New plans are chosen from the new statistics as soon as it
  commits, on the writer and on every Aurora reader.

## Step 1 -- Analyze the specific tables, one at a time

```sql
-- Run on the WRITER. Readers are in recovery and cannot update catalogs.
SET statement_timeout = 0;        -- only if a role default would cut it short

ANALYZE VERBOSE public.orders;
ANALYZE VERBOSE public.trades;
```

- Name the tables explicitly. Never issue a bare `ANALYZE;` on a production
  exchange cluster -- it analyzes everything, including tables that do not need it.
- `VERBOSE` reports the sample size and row count per table, which is useful
  evidence for the change record.
- Run them sequentially rather than in parallel sessions, so several large samples
  do not compete for storage I/O at once.
- For a single very large table during trading hours, consider analyzing specific
  columns only:

  ```sql
  ANALYZE public.trades (market_symbol, executed_at);
  ```

## Step 2 -- Verify it took effect

Re-run script 01 of this workflow. `last_analyze` must now be current and
`n_mod_since_analyze` must have reset to approximately zero. Then re-run script 04
and confirm the stored distribution now matches reality.

Finally, re-capture the plan for the affected query with plain `EXPLAIN` (no
`ANALYZE` needed) and confirm the estimates and the plan shape changed as expected.

## Step 3 -- Stop it recurring

```sql
-- Make autoanalyze trigger on a sane absolute number of modifications for a very
-- large table, instead of on 10% of an enormous row count.
-- Catalog-only change, but it takes a brief ACCESS EXCLUSIVE lock: schedule it
-- like any other DDL on a hot table.
ALTER TABLE public.trades SET (autovacuum_analyze_scale_factor = 0.01);

-- Re-enable autovacuum/autoanalyze on a table where it was disabled during a past
-- incident and never restored.
ALTER TABLE public.order_book_snapshots SET (autovacuum_enabled = true);
```

And make the migration pipeline do it automatically: every migration that backfills
or bulk-modifies a table should end with a targeted `ANALYZE` of that table, so the
planner never spends time working from a pre-migration picture of the data.

## Do not

- Do not run a bare database-wide `ANALYZE;` as a routine remedy.
- Do not run `VACUUM ANALYZE` when only statistics are stale: `VACUUM` is far more
  expensive and is not what the problem calls for.
- Do not run `ANALYZE` concurrently on many large tables during peak trading -- the
  sampling I/O competes with the order path.
- Do not raise `default_statistics_target` cluster-wide as a substitute for
  analyzing the specific table that is stale.
