# Adding a Column to a Large Table

**Category:** Schema Changes and DDL | **Workflow:** `schema-changes/add-column-large-table`

## 1. Problem Description

Adding a column to a large production table is the schema change most often assumed to be trivial, and most of the time it now is -- but the exceptions are severe and they are not obvious from the statement text. Since PostgreSQL 11, `ADD COLUMN` with a constant default is a catalog-only operation: the default is stored once in `pg_attribute` and materialized lazily as rows are updated, so the statement takes an `AccessExclusiveLock` for milliseconds regardless of table size. But a *volatile* default such as `now()` or `gen_random_uuid()`, a `GENERATED ALWAYS AS ... STORED` column, or adding `NOT NULL` in the same statement without a default, each force a full table rewrite that holds that lock for hours on an exchange-scale table. This workflow tells the two cases apart before the statement is run, not after.

## 2. Typical Symptoms

- A feature requires a new column on orders, trades, wallets, or ledger_entries.
- A previous `ADD COLUMN` on a large table unexpectedly blocked the application for a long period.
- A migration is being reviewed and it is unclear whether it will rewrite the table.
- A column needs both a default and a `NOT NULL` constraint, and the safe ordering is not obvious.
- A computed column is wanted and the choice between a stored generated column and an application-maintained one has not been made.

## 3. Business Impact

- A rewriting `ADD COLUMN` on the orders table blocks all reads and writes for the duration -- a full trading outage on that table.
- The same statement doubles the table's storage for its duration and permanently raises the Aurora volume high-water mark.
- A rewrite generates WAL proportional to the whole table, spiking reader lag and causing customer-facing stale reads.
- Conversely, refusing to add columns at all because of a bad past experience blocks product delivery unnecessarily, since the safe form really is safe.

## 4. Possible Root Causes

- N/A -- this is a planned change workflow. The risk comes entirely from which form of `ADD COLUMN` is used.

## 5. Investigation Strategy

1. Measure the table so the cost of the rewrite form is known in concrete terms, not as an abstraction.
2. Inventory the existing columns, including which earlier additions used a fast default, to confirm the table is in a normal state.
3. Classify the intended statement against the semantics reference: constant default, volatile default, generated, or `NOT NULL`.
4. Check the current lock picture immediately before executing.
5. Execute the safe form through the runbook, splitting default and `NOT NULL` into separate steps where needed.
6. Verify afterwards that the column exists with the intended definition and that a fast default was used where expected.

## 6. Prerequisites

- Table ownership; `pg_monitor` for the investigation scripts.
- The exact intended column definition, including type, default expression, and nullability -- the default expression in particular decides everything.
- Awareness of the PostgreSQL version's behavior: the fast-default optimization exists from PostgreSQL 11, so it is available on Aurora PostgreSQL 17.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_target_table_size_and_state.sql`](scripts/01_target_table_size_and_state.sql) -- Measures the target table so the cost of the rewriting form is understood in concrete terms before a form is chosen.
2. [`scripts/02_existing_column_inventory.sql`](scripts/02_existing_column_inventory.sql) -- Inventories the table's current columns, including which earlier additions used a PostgreSQL fast default.
3. [`scripts/03_current_lock_activity.sql`](scripts/03_current_lock_activity.sql) -- Shows the current lock picture and long-running transactions immediately before the statement is executed.
4. [`scripts/04_add_column_semantics_reference.md`](scripts/04_add_column_semantics_reference.md) -- Reference classification of every ADD COLUMN form by rewrite behavior, with the reasoning behind the PostgreSQL fast-default optimization.
5. [`scripts/05_add_column_execution_runbook.md`](scripts/05_add_column_execution_runbook.md) -- The guarded DDL runbook for adding a column safely, including how to get a per-row default value without a rewrite.
6. [`scripts/06_post_change_verification.sql`](scripts/06_post_change_verification.sql) -- Confirms the new column exists with the intended definition and that the fast-default optimization was actually used.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- The PostgreSQL 11 fast-default optimization is fully available on Aurora PostgreSQL 17, so a constant-default `ADD COLUMN` really is a millisecond operation regardless of table size.
- A rewriting `ADD COLUMN` generates WAL proportional to the whole table, which every Aurora reader must apply from the shared storage volume -- expect significant reader lag throughout.
- The temporary second copy created by a rewrite permanently raises the Aurora volume high-water mark even after the original is released.
- An Aurora failover during a rewriting `ADD COLUMN` rolls the statement back entirely. Nothing is corrupted, but the work is lost -- another reason to prefer the fast form plus backfill.

## 8. Interpretation Guide

- The decisive question is whether the default expression is constant. `DEFAULT 0`, `DEFAULT false`, `DEFAULT 'pending'` are constant and use the fast path. `DEFAULT now()`, `DEFAULT gen_random_uuid()`, `DEFAULT random()` are volatile, must be evaluated per row, and force a full rewrite.
- `ADD COLUMN ... NOT NULL` with no default fails outright if the table has any rows, because existing rows would violate it. `ADD COLUMN ... NOT NULL DEFAULT <constant>` works and is still fast-path on PostgreSQL 11 and later.
- `GENERATED ALWAYS AS (...) STORED` always rewrites -- the value must be computed and physically stored for every existing row. If the table is large, add a plain column and backfill it in batches instead.
- A column added with a fast default shows `atthasmissing = true` in `pg_attribute`. That flag is the proof the optimization was actually used, and it is how you verify after the fact rather than assuming.
- `DROP COLUMN` is also catalog-only -- it marks the column dropped without touching the rows. The space is reclaimed lazily by vacuum as rows are rewritten for other reasons, so do not expect an immediate size reduction.
- Adding a column with a fast default does not slow down reads: PostgreSQL substitutes the missing value transparently when it reads a row written before the column existed.
- On a partitioned table, `ADD COLUMN` on the parent recurses to every partition and locks all of them in one transaction. The fast path still applies per partition, but the lock footprint is the whole table.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If a rewriting `ADD COLUMN` is currently running and blocking the application, cancel it. The statement is fully transactional, so it rolls back cleanly and leaves nothing behind.

**Short-term remediation** (hours to days):

- Replace a volatile default with a constant default plus a batched backfill -- this converts a multi-hour blocking rewrite into a millisecond change plus an online backfill.
- Split `ADD COLUMN` and `SET NOT NULL` into separate steps, using the validated-check pattern so the `NOT NULL` never needs a blocking scan.
- Replace a stored generated column with a plain column maintained by the application or a trigger, if the table is too large for the rewrite.

**Long-term engineering fix** (days to weeks):

- Add a migration review rule: any `ADD COLUMN` with a non-constant default or a `GENERATED ... STORED` clause is rejected on tables above an agreed size threshold.
- Standardize on constant defaults plus backfill as the house pattern, so the safe form is the habitual one.
- Keep the largest tables partitioned so even a rewriting change can be applied one partition at a time.

## 10. Production Safety

- All `.sql` scripts here are read-only. The DDL lives in the `.md` runbooks.
- Always set `lock_timeout` before the statement, even for the fast form, so it cannot form a lock queue while waiting.
- Never add a column with a volatile default to a large table in a single statement. Split it.
- The backfill that replaces a volatile default must be batched and committed in chunks, never one `UPDATE` across the whole table.
- On a partitioned table, confirm the recursion behavior before running anything against the parent.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- The proposed statement requires a rewrite on a table on the live trading path and the owning team is pushing to run it as-is.
- The column is a financial field whose default value affects settlement or reconciliation logic -- that needs compliance review, not just a DBA.
- The table is partitioned with a large number of partitions, making even the fast form a wide lock footprint.
- An earlier `ADD COLUMN` on this table caused an incident whose cause was never established -- resolve that before adding another.

## 12. Related Issues

- [large-table-ddl](../large-table-ddl/README.md)
- [column-type-change](../column-type-change/README.md)
- [ddl-lock-investigation](../ddl-lock-investigation/README.md)
- [ddl-blocking](../../concurrency-and-locking/ddl-blocking/README.md)
- [table-growth](../../storage-and-capacity/table-growth/README.md)
- [partition-existing-large-table](../../partitioning/partition-existing-large-table/README.md)
