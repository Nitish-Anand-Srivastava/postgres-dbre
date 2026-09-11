# 05_large_table_index_build_runbook

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `05_large_table_index_build_runbook.md` |
| Purpose | The guarded DDL runbook for building an index on a very large table, including partial and covering index alternatives. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only (the query reads/writes state that only exists or is meaningful on the writer) |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | Varies by step -- read each step's own warning before executing it. |
| Required privileges | Table owner, or a role granted the `MAINTAIN` privilege on the table (PostgreSQL 16+), or a role with `pg_maintain` membership. DDL variants additionally require the privileges needed for the specific DDL statement (e.g. ownership to ALTER TABLE). |
| Prerequisites | The read-only investigation scripts for this workflow have been completed and reviewed; a change ticket exists; a second engineer is present; and the rollback path has been agreed before the first statement is executed. |
| Execution order | Step 05 of workflow `schema-changes/add-index-large-table` |
| Related scripts | 06_build_progress_and_validity.sql, ../concurrent-index-build/README.md |

## How to interpret / use this runbook

Start from the partial index section rather than the plain build -- on exchange data the queries that matter almost always filter on a status, a date window, or an account subset, and a partial index delivers the same plan improvement at a fraction of the build time, the storage, and the permanent write cost. Whatever form you choose, the build must be concurrent and must not be inside a transaction block. Budget for the cleanup a cancellation would require before you start, and treat customer-visible reader lag as an unconditional reason to stop. Substitute your real schema, table, index name, column list, and predicate into the templates before running anything.

---

## Prefer a smaller index first

Before building a plain index over an entire multi-hundred-gigabyte table, check whether a smaller one satisfies the query. On exchange data it usually does.

### Partial index -- usually the right answer

```sql
-- Open orders are a tiny fraction of all orders ever placed. This index is a
-- fraction of the size, builds in a fraction of the time, and -- critically --
-- costs nothing to maintain for the overwhelming majority of rows, because rows
-- outside the predicate are never indexed at all.
CREATE INDEX CONCURRENTLY idx_orders_open_by_account
    ON public.orders (account_id, created_at DESC)
    WHERE status IN ('open', 'partially_filled');
```

The planner only uses a partial index when it can prove the query's predicate implies the index predicate, so the query must filter on `status` with compatible values. Confirm with `EXPLAIN` on a representative query before committing to the build.

### Covering index -- when an index-only scan is the goal

```sql
-- INCLUDE columns are stored in the leaf pages but not used for ordering or
-- searching. This can turn a heap fetch into an index-only scan, at the cost of
-- a larger index. Only worth it when the query genuinely returns those columns
-- and the table is well vacuumed (the visibility map must be current for an
-- index-only scan to avoid the heap).
CREATE INDEX CONCURRENTLY idx_trades_account_covering
    ON public.trades (account_id, executed_at DESC)
    INCLUDE (quantity, price);
```

---

## The build

| Property | Value |
|---|---|
| Lock level | `ShareUpdateExclusiveLock` |
| Blocks reads | No |
| Blocks writes | No |
| Blocks autovacuum on this table | **Yes, for the whole build** |
| Runs inside a transaction block | **No -- rejected** |
| Rollback | None. Failure leaves an INVALID index to drop. |

### Step 1 -- session setup

```sql
SET lock_timeout = '5s';
SET statement_timeout = 0;         -- must not be killed part-way
SET maintenance_work_mem = '4GB';  -- keep the sort off local storage if possible
```

On a very large table, `maintenance_work_mem` is the difference between an
in-memory sort and one that spills to per-instance local storage -- which is both
much slower and a `FreeLocalStorage` risk on Aurora.

### Step 2 -- clear the blockers

Re-run `large-table-ddl` script 04. A concurrent build waits for every transaction
that started before each of its two phase boundaries, including transactions that
never touch this table. On a build measured in hours, a single idle-in-transaction
session can stall it indefinitely.

### Step 3 -- build

```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ledger_entries_account_posted
    ON public.ledger_entries (account_id, posted_at DESC);
```

- **Blocking risk:** the build blocks no application traffic, but it blocks autovacuum on this table for its entire duration. On a high-write table a six-hour build means six hours of dead tuple accumulation -- plan a vacuum afterwards.
- **Transaction behavior:** not permitted inside a transaction block. Disable your migration framework's implicit transaction or run it by hand.
- **Rollback:** none. Cancellation, timeout, session loss, or an Aurora failover leaves an INVALID index that must be dropped before any retry.
- **Production considerations:** monitor Aurora reader lag throughout. Customer-visible lag is grounds to cancel -- the index can wait, stale balances cannot.

### Step 4 -- monitor

From a second session, run `06_build_progress_and_validity.sql` repeatedly and
watch the `phase` column rather than the percentages.

### Step 5 -- after the build

```sql
-- 1. Refresh statistics so the planner knows about the new index's column
--    correlation immediately rather than waiting for autoanalyze.
ANALYZE public.ledger_entries;

-- 2. Vacuum, because the build blocked autovacuum on this table throughout.
--    Plain VACUUM only -- never VACUUM FULL on a production exchange table.
VACUUM (ANALYZE) public.ledger_entries;
```

Then confirm over the following days that the query you built the index for actually uses it. An index that is never scanned is a permanent write-amplification cost with no benefit, and should be dropped through the drop-index-safely workflow rather than left in place out of sunk-cost attachment.
