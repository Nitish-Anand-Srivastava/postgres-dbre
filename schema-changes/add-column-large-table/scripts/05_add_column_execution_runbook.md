# 05_add_column_execution_runbook

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `05_add_column_execution_runbook.md` |
| Purpose | The guarded DDL runbook for adding a column safely, including how to get a per-row default value without a rewrite. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only (the query reads/writes state that only exists or is meaningful on the writer) |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | Varies by step -- read each step's own warning before executing it. |
| Required privileges | Table owner, or a role granted the `MAINTAIN` privilege on the table (PostgreSQL 16+), or a role with `pg_maintain` membership. DDL variants additionally require the privileges needed for the specific DDL statement (e.g. ownership to ALTER TABLE). |
| Prerequisites | The read-only investigation scripts for this workflow have been completed and reviewed; a change ticket exists; a second engineer is present; and the rollback path has been agreed before the first statement is executed. |
| Execution order | Step 05 of workflow `schema-changes/add-column-large-table` |
| Related scripts | 04_add_column_semantics_reference.md, 06_post_change_verification.sql |

## How to interpret / use this runbook

Use Pattern A whenever the default is constant or absent -- that covers most real requirements and is safe during trading hours with the lock timeout set. Reach for Pattern B the moment someone asks for now() or gen_random_uuid() as a default on a large table; it delivers the same end state with no blocking rewrite. Pattern C exists so that tightening to NOT NULL never needs a blocking scan, and there is no production case where the bare SET NOT NULL is preferable. Substitute your real schema, table, column, and default values into every template before running anything.

---

## Pattern A -- the safe form (constant or no default)

```sql
BEGIN;
  SET LOCAL lock_timeout = '3s';

  ALTER TABLE public.orders
      ADD COLUMN settlement_status text NOT NULL DEFAULT 'pending';
COMMIT;
```

- **Lock level:** `AccessExclusiveLock`, held for milliseconds regardless of table size.
- **Blocking risk:** near zero with the timeout set. Without it, the statement can queue behind a long-running transaction and stall every later query on the table -- the classic 'a trivial migration took the site down' incident.
- **Transaction behavior:** fully transactional and combinable with other DDL.
- **Rollback:** clean. `ROLLBACK`, a crash, or an Aurora failover all leave no trace.
- **Production considerations:** safe during trading hours. If it fails with `canceling statement due to lock timeout`, that is the system protecting you -- retry in a loop rather than raising the timeout.

---

## Pattern B -- a per-row value without a rewrite

When the requirement is really 'every row needs its own value' -- a creation timestamp, a generated identifier -- do not use a volatile default. Split it into a cheap DDL step and an online backfill.

```sql
-- Step 1: add the column with NO default. Milliseconds, catalog only.
BEGIN;
  SET LOCAL lock_timeout = '3s';
  ALTER TABLE public.deposits ADD COLUMN external_ref uuid;
COMMIT;

-- Step 2: set the default for NEW rows only. Also catalog only.
BEGIN;
  SET LOCAL lock_timeout = '3s';
  ALTER TABLE public.deposits ALTER COLUMN external_ref SET DEFAULT gen_random_uuid();
COMMIT;

-- Step 3: backfill existing rows in small committed batches. Never one UPDATE
-- across the whole table: that holds a long-running transaction (blocking vacuum
-- cleanup database-wide), produces one enormous WAL burst that spikes Aurora
-- reader lag, and creates a dead tuple for every row at once.
UPDATE public.deposits
SET external_ref = gen_random_uuid()
WHERE external_ref IS NULL
  AND id BETWEEN :batch_start AND :batch_end;
-- COMMIT after each batch, advance the watermark, repeat. Monitor reader lag and
-- dead tuple growth between batches and slow down if either climbs.
```

- **Lock level:** steps 1 and 2 take `AccessExclusiveLock` for milliseconds; step 3 takes ordinary row locks only.
- **Blocking risk:** minimal at every step. The backfill's real cost is WAL volume and dead tuples, not locking.
- **Transaction behavior:** keep the three steps in separate transactions; the backfill must commit per batch.
- **Rollback:** steps 1 and 2 roll back cleanly. The backfill can be abandoned part-way, leaving the column partly populated and no harm done.
- **Production considerations:** the backfill can safely take days. There is no deadline and slower is safer.

---

## Pattern C -- adding NOT NULL after the fact

If the column was added nullable and must become `NOT NULL` once backfilled, do not use a bare `SET NOT NULL` on a large table -- it scans every row while holding `AccessExclusiveLock`. Use the validated-check pattern instead:

```sql
-- Step 1: cheap constraint, no scan. AccessExclusiveLock for milliseconds.
BEGIN;
  SET LOCAL lock_timeout = '3s';
  ALTER TABLE public.deposits
      ADD CONSTRAINT deposits_external_ref_nn
      CHECK (external_ref IS NOT NULL) NOT VALID;
COMMIT;

-- Step 2: scan without blocking. ShareUpdateExclusiveLock -- reads and writes
-- both continue normally. Takes as long as it needs.
ALTER TABLE public.deposits VALIDATE CONSTRAINT deposits_external_ref_nn;

-- Step 3: PostgreSQL 12+ uses the validated CHECK to prove no NULLs exist, so
-- SET NOT NULL skips its own scan entirely and is a metadata operation.
BEGIN;
  SET LOCAL lock_timeout = '3s';
  ALTER TABLE public.deposits ALTER COLUMN external_ref SET NOT NULL;
  ALTER TABLE public.deposits DROP CONSTRAINT deposits_external_ref_nn;
COMMIT;
```

- **Rollback:** each step is independently reversible. If step 2 finds a NULL it fails and the constraint simply remains `NOT VALID` -- nothing is broken, and you have learned the backfill is incomplete.

---

## Partitioned tables

`ADD COLUMN` on a partitioned parent recurses into every partition and holds `AccessExclusiveLock` on all of them in a single transaction. The fast-default optimization still applies per partition, so the operation remains fast, but the lock footprint is the entire table at once. On a table with hundreds of partitions, run it with a short lock timeout in the quietest window available and be ready to retry.
