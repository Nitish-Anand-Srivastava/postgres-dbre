# 06_large_table_ddl_execution_runbook

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `06_large_table_ddl_execution_runbook.md` |
| Purpose | The guarded execution runbook: lock-timeout-and-retry for fast DDL, the two-step pattern for constraints, and build-alongside-and-swap for rewrites. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only (the query reads/writes state that only exists or is meaningful on the writer) |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | Varies by step -- read each step's own warning before executing it. |
| Required privileges | Table owner, or a role granted the `MAINTAIN` privilege on the table (PostgreSQL 16+), or a role with `pg_maintain` membership. DDL variants additionally require the privileges needed for the specific DDL statement (e.g. ownership to ALTER TABLE). |
| Prerequisites | The read-only investigation scripts for this workflow have been completed and reviewed; a change ticket exists; a second engineer is present; and the rollback path has been agreed before the first statement is executed. |
| Execution order | Step 06 of workflow `schema-changes/large-table-ddl` |
| Related scripts | 05_lock_level_and_rewrite_reference.md, 03_current_lock_activity.sql |

## How to interpret / use this runbook

Choose the pattern from the classification in script 05 and do not improvise a fourth one. Pattern 1 covers most schema changes and is safe during trading hours as long as the lock timeout is set. Pattern 2 exists specifically so that constraint additions never need a blocking scan, and there is no production situation where the one-step form is preferable. Pattern 3 is a migration project rather than a statement -- if your change needs it, plan it as such. Substitute your real schema, table, column, and constraint names into every template before running anything, and execute one statement at a time with a second session standing by to cancel.

---

## Pattern 1 -- lock timeout and retry (for metadata-only DDL)

Use for anything classified as metadata-only in script 05. The point is that the
statement either gets its lock immediately or fails harmlessly, and never forms
a queue that stalls the application.

```sql
BEGIN;
  -- The single most important line in this entire category. Without it, a
  -- statement that cannot get its lock queues, and every subsequent query on
  -- the table queues behind it -- a total application stall caused by a
  -- statement that has not done any work at all.
  SET LOCAL lock_timeout = '3s';

  ALTER TABLE public.orders ADD COLUMN settlement_batch_id bigint;
COMMIT;
```

If it fails with `canceling statement due to lock timeout`, that is the system
working correctly. Wait, check `04_long_running_transactions.sql`, and retry.
Retry in a loop with a short sleep rather than raising the timeout -- on a busy
table the window usually appears within a few attempts.

- **Lock level:** `AccessExclusiveLock`, held for milliseconds.
- **Blocking risk:** near zero with the timeout set; severe without it.
- **Transaction behavior:** fully transactional and combinable with other DDL in the same transaction.
- **Rollback:** clean. `ROLLBACK` undoes it entirely.
- **Production considerations:** safe during trading hours *with* the timeout. Never without.

---

## Pattern 2 -- two-step constraint addition

Use for `CHECK`, `FOREIGN KEY`, and `SET NOT NULL`. Splits one long blocking scan
into a millisecond lock plus a non-blocking scan.

```sql
-- Step 1: add the constraint without checking existing rows.
-- AccessExclusiveLock, milliseconds, no scan. New and updated rows are enforced
-- from this moment on.
BEGIN;
  SET LOCAL lock_timeout = '3s';
  ALTER TABLE public.withdrawals
      ADD CONSTRAINT withdrawals_amount_positive
      CHECK (amount > 0) NOT VALID;
COMMIT;

-- Step 2: validate existing rows. ShareUpdateExclusiveLock -- reads and writes
-- both continue normally while this scans the whole table. Run it separately,
-- and it can take as long as it needs to.
ALTER TABLE public.withdrawals VALIDATE CONSTRAINT withdrawals_amount_positive;
```

The same pattern for a foreign key:

```sql
BEGIN;
  SET LOCAL lock_timeout = '3s';
  ALTER TABLE public.ledger_entries
      ADD CONSTRAINT ledger_entries_account_fk
      FOREIGN KEY (account_id) REFERENCES public.accounts (id) NOT VALID;
COMMIT;

ALTER TABLE public.ledger_entries VALIDATE CONSTRAINT ledger_entries_account_fk;
```

And for `SET NOT NULL` on PostgreSQL 12 and later, where a validated check constraint lets the `SET NOT NULL` skip its scan entirely:

```sql
BEGIN;
  SET LOCAL lock_timeout = '3s';
  ALTER TABLE public.trades
      ADD CONSTRAINT trades_venue_id_not_null
      CHECK (venue_id IS NOT NULL) NOT VALID;
COMMIT;

ALTER TABLE public.trades VALIDATE CONSTRAINT trades_venue_id_not_null;

BEGIN;
  SET LOCAL lock_timeout = '3s';
  ALTER TABLE public.trades ALTER COLUMN venue_id SET NOT NULL;
  -- The validated CHECK proves no NULLs exist, so no table scan is needed here.
  -- The redundant CHECK can then be dropped.
  ALTER TABLE public.trades DROP CONSTRAINT trades_venue_id_not_null;
COMMIT;
```

- **Lock level:** step 1 `AccessExclusiveLock` (milliseconds); step 2 `ShareUpdateExclusiveLock` (duration of the scan, blocking nothing).
- **Blocking risk:** minimal at both steps.
- **Transaction behavior:** each step is transactional. Keep them in separate transactions -- combining them defeats the purpose entirely.
- **Rollback:** step 1 rolls back cleanly. If step 2 fails, the constraint simply remains `NOT VALID` and can be validated again later; nothing is broken.
- **Production considerations:** a `NOT VALID` constraint still enforces new writes, so leaving it unvalidated for a while is a legitimate intermediate state.

---

## Pattern 3 -- build alongside and swap (for rewrites)

For anything classified as a full rewrite on a table too large to lock. The principle is to do all the expensive work on a copy nobody is using, then make the switch a millisecond metadata operation.

1. Create the new table with the desired structure (empty, no traffic, no lock on the original).
2. Create its indexes and constraints while it is still empty and cheap.
3. Backfill in small committed batches -- never one large transaction, which would hold a long-running transaction, block vacuum cleanup everywhere, and generate one enormous WAL burst that spikes reader lag.
4. Keep the copy current with ongoing writes via a trigger-based dual write or logical replication, active from before the backfill starts until after cutover.
5. Validate row counts and checksums between the two, during a brief write-quiesce so both sides are compared at a consistent point.
6. Swap with an atomic rename inside one short transaction with a lock timeout.
7. Keep the old table (renamed, not dropped) for a rollback window.

```sql
-- Step 6, the only step that takes a strong lock. Typically milliseconds,
-- because all the data work is already done.
BEGIN;
  SET LOCAL lock_timeout = '5s';
  ALTER TABLE public.orders RENAME TO orders_pre_change_backup;
  ALTER TABLE public.orders_new RENAME TO orders;
COMMIT;
```

- **Lock level:** `AccessExclusiveLock` for the rename only, held for milliseconds.
- **Blocking risk:** confined to that one short transaction. In-flight queries wait or fail fast, then succeed immediately after commit.
- **Transaction behavior:** the swap must be one atomic transaction so there is never a moment with no `orders` table.
- **Rollback:** rename back. This is why the original is renamed rather than dropped, and why it should be kept for a full rollback window before cleanup.
- **Production considerations:** the full pattern with backfill, sync, and validation is documented step by step in the partitioning category's large-table migration runbook -- the mechanics are identical whether the goal is partitioning or a column type change.

---

## Always, for every pattern

- Run `03_current_lock_activity.sql` and `04_long_running_transactions.sql` immediately before executing, not an hour earlier.
- Have a second session open and ready to cancel the statement if the application starts stalling.
- Never issue production DDL without `lock_timeout`.
- Re-run `02_dependent_objects_inventory.sql` afterwards and confirm nothing was left invalid or unvalidated.
