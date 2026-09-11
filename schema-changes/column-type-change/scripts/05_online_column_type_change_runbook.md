# 05_online_column_type_change_runbook

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `05_online_column_type_change_runbook.md` |
| Purpose | The guarded online add-and-swap runbook for a type change that requires a rewrite, avoiding any long exclusive lock. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only (the query reads/writes state that only exists or is meaningful on the writer) |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | Varies by step -- read each step's own warning before executing it. |
| Required privileges | Table owner, or a role granted the `MAINTAIN` privilege on the table (PostgreSQL 16+), or a role with `pg_maintain` membership. DDL variants additionally require the privileges needed for the specific DDL statement (e.g. ownership to ALTER TABLE). |
| Prerequisites | The read-only investigation scripts for this workflow have been completed and reviewed; a change ticket exists; a second engineer is present; and the rollback path has been agreed before the first statement is executed. |
| Execution order | Step 05 of workflow `schema-changes/column-type-change` |
| Related scripts | 06_post_change_verification.sql, ../concurrent-index-build/README.md |

## How to interpret / use this runbook

Work through the steps in order and treat step 5 as an absolute gate -- on a financial table a non-zero mismatch is a data-integrity finding and must be understood before the swap, never explained away to keep the migration moving. The pattern's key property is that every individual step is short and reversible, which is what makes it survivable on a 24/7 platform and resilient to an unplanned Aurora failover. Steps 1 through 5 run fully online and can take as long as they need; only step 6 takes a strong lock, and only for milliseconds. Substitute your real schema, table, column, and type names into every statement before running it.

---

## Principle

A rewriting `ALTER COLUMN ... TYPE` holds an `AccessExclusiveLock` for its entire
duration. The way around that is not to make the rewrite faster -- it is to do
the expensive work in a new column that nobody is reading, and make the switch a
millisecond metadata operation.

The worked example below widens `public.trades.id` from `integer` to `bigint`,
which is the canonical exchange case. Adapt names and types to your change.

---

## Step 1 -- add the new column

```sql
BEGIN;
  SET LOCAL lock_timeout = '3s';
  ALTER TABLE public.trades ADD COLUMN id_new bigint;
COMMIT;
```

- **Lock level:** `AccessExclusiveLock`, milliseconds. Adding a nullable column with no default is a catalog-only change on PostgreSQL 11 and later.
- **Blocking risk:** near zero with the timeout.
- **Rollback:** clean -- drop the column.

## Step 2 -- keep the new column in sync for ongoing writes

```sql
CREATE OR REPLACE FUNCTION public.trades_sync_id_new() RETURNS trigger AS $$
BEGIN
    NEW.id_new := NEW.id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_trades_sync_id_new
    BEFORE INSERT OR UPDATE ON public.trades
    FOR EACH ROW EXECUTE FUNCTION public.trades_sync_id_new();
```

- **Lock level:** `CREATE TRIGGER` takes a `ShareRowExclusiveLock` -- it blocks writes briefly but not reads. Schedule this one statement for a quieter moment and keep a lock timeout set.
- **Blocking risk:** brief, writes only.
- **Rollback:** drop the trigger and the function.
- **Production considerations:** this trigger runs on every write to the table for the duration of the migration, so it must be trivially cheap. Measure its overhead on the write path before leaving it in place.

## Step 3 -- backfill in batches

```sql
-- Repeat, advancing the watermark, until no rows remain. Keep each batch small
-- enough to finish in well under a second. Never a single UPDATE across the
-- whole table: that holds one long-running transaction (blocking vacuum cleanup
-- database-wide) and produces one enormous WAL burst that spikes reader lag.
UPDATE public.trades
SET id_new = id
WHERE id_new IS NULL
  AND id BETWEEN :batch_start AND :batch_end;
-- COMMIT after each batch. Monitor Aurora reader lag between batches and slow
-- down if it climbs. Each updated row is a new row version, so dead tuples
-- accumulate throughout -- let autovacuum keep up rather than racing it.
```

- **Lock level:** ordinary row locks only. No table-level blocking.
- **Blocking risk:** low, but the write volume is real -- this is the step that generates the WAL and the dead tuples.
- **Rollback:** abandon at any point; the new column is simply left partly populated and unused.
- **Production considerations:** this step can safely take days on a very large table. Slower is safer, and there is no deadline until the ceiling itself.

## Step 4 -- build the replacement index concurrently

```sql
CREATE UNIQUE INDEX CONCURRENTLY trades_pkey_new ON public.trades (id_new);
```

Not inside a transaction block. See the concurrent-index-build workflow for the
full operational detail and the failure modes.

## Step 5 -- validate before the swap

```sql
-- Read-only. Must return zero before proceeding. Run during a brief write
-- quiesce so both columns are compared at a consistent point in time.
SELECT count(*) AS rows_not_yet_synced
FROM public.trades
WHERE id_new IS DISTINCT FROM id;
```

**Do not proceed with a non-zero result.** On a financial table an unexplained
mismatch is a data-integrity finding, not a migration inconvenience.

## Step 6 -- swap

```sql
BEGIN;
  SET LOCAL lock_timeout = '5s';

  ALTER TABLE public.trades DROP CONSTRAINT trades_pkey;
  ALTER TABLE public.trades ADD CONSTRAINT trades_pkey
      PRIMARY KEY USING INDEX trades_pkey_new;

  ALTER TABLE public.trades DROP COLUMN id;
  ALTER TABLE public.trades RENAME COLUMN id_new TO id;

  DROP TRIGGER trg_trades_sync_id_new ON public.trades;
COMMIT;
```

- **Lock level:** `AccessExclusiveLock`, held for milliseconds -- every one of these is a catalog operation because all the data work is already done.
- **Blocking risk:** confined to this one short transaction. In-flight queries wait or fail fast, then succeed immediately after commit.
- **Transaction behavior:** must be one atomic transaction so there is never a moment where the table lacks a primary key or the column.
- **Rollback:** `ROLLBACK` restores everything, since it is all one transaction. This is the strongest safety property of the whole pattern.
- **Production considerations:** run it in the lowest-traffic window available despite being fast, because a brief connection-retry blip is still expected.

## Step 7 -- afterwards

- Recreate any dependent views identified in `02_dependent_objects_inventory.sql`.
- Widen the backing sequence if there is one: `ALTER SEQUENCE public.trades_id_seq AS bigint;`
- Coordinate the same widening on every child table with a foreign key referencing this column -- until that is done, the referencing columns are still `integer` and the ceiling problem has only moved.
- Run `06_post_change_verification.sql` and confirm the new type and that no index was left invalid.
- Vacuum the table: the batched backfill created one dead tuple per row.
