# 10_cutover_procedure

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `10_cutover_procedure.md` |
| Purpose | Performs the brief, controlled cutover from the original table to the new partitioned table using an atomic rename swap. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only (the query reads/writes state that only exists or is meaningful on the writer) |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | Varies by step -- read each step's own warning before executing it. |
| Required privileges | Table owner, or a role granted the `MAINTAIN` privilege on the table (PostgreSQL 16+), or a role with `pg_maintain` membership. DDL variants additionally require the privileges needed for the specific DDL statement (e.g. ownership to ALTER TABLE). |
| Prerequisites | Full read-only investigation for this workflow completed; maintenance window and second engineer approval obtained. |
| Execution order | Step 10 of workflow `partitioning/partition-existing-large-table` |
| Related scripts | 11_rollback_plan.md |

## How to interpret / use this runbook

This is the highest-risk single step in the entire runbook -- have the rollback runbook (script 11) open and ready before starting, and execute during your lowest-traffic window.

---

## Cutover procedure (the only step requiring a brief exclusive lock)

Perform during your lowest-traffic window despite the swap itself being fast, since a short connection-draining/retry blip is still expected for in-flight transactions.

```sql
BEGIN;
  -- Optional: set a short lock_timeout so this transaction fails fast rather
  -- than queuing indefinitely if an unexpected long-running transaction is
  -- holding a conflicting lock on the table at this moment.
  SET LOCAL lock_timeout = '5s';

  ALTER TABLE public.orders RENAME TO orders_pre_partition_backup;
  ALTER TABLE public.orders_partitioned RENAME TO orders;

  -- If using Option A (trigger-based sync) from script 08, drop the now-obsolete
  -- trigger inside this same transaction so no further dual-writes occur once
  -- the rename takes effect:
  DROP TRIGGER IF EXISTS trg_sync_orders_partitioned ON public.orders_pre_partition_backup;
COMMIT;
```

Both `ALTER TABLE ... RENAME` statements take `AccessExclusiveLock`, but on already-open, already-indexed tables this is typically a millisecond-scale metadata operation -- the actual data was already fully backfilled and validated in prior steps. Application connections attempting to use the table during this brief window will wait (or fail-fast if a client-side statement timeout is set) and succeed immediately after COMMIT.

Immediately after cutover: run script 09's validation query again against the new `public.orders` (now the renamed partitioned table) and a fresh application smoke test before declaring the migration complete.
