# Changing a Column Type on a Production Table

**Category:** Schema Changes and DDL | **Workflow:** `schema-changes/column-type-change`

## 1. Problem Description

A column's data type must change -- the classic case on an exchange being an `integer` surrogate key on the trades or ledger table approaching the two-billion ceiling and needing to become `bigint`, or a `numeric` price column needing more scale. `ALTER TABLE ... ALTER COLUMN ... TYPE` is deceptively short for what it does: for most type changes it rewrites every row of the table and rebuilds every index, holding an `AccessExclusiveLock` throughout, which on a large exchange table is an outage measured in hours. A small number of type changes are metadata-only and genuinely instant. This workflow establishes which category your change falls into, inventories everything that depends on the column, and provides the online add-column-and-swap pattern for the cases where a rewrite is not acceptable.

## 2. Typical Symptoms

- An `integer` primary key or foreign key column is approaching the 2,147,483,647 ceiling on a high-volume table.
- A `numeric` or `decimal` price or amount column needs more precision or scale to support a new instrument.
- A `varchar(n)` column needs a larger length limit, or needs to become unbounded `text`.
- A timestamp column without time zone needs to become `timestamptz` after a timezone-correctness bug.
- An `ALTER COLUMN ... TYPE` was attempted and had to be cancelled because it blocked the application.
- Application inserts are failing with 'integer out of range' -- at which point the change is no longer optional and the sequence ceiling has already been reached.

## 3. Business Impact

- An integer key exhausting its range causes hard insert failures -- on a trades or ledger table that means the exchange cannot record activity, which is a full trading outage.
- A naive rewrite of a large table holds an exclusive lock for hours, which is itself a full outage on that table.
- A rewrite doubles storage for its duration and generates WAL proportional to the whole table, spiking reader lag and permanently raising the Aurora volume high-water mark.
- Precision changes on financial columns carry correctness risk: a wrong scale on an amount column is a reconciliation and regulatory problem, not just a schema one.

## 4. Possible Root Causes

- N/A -- this is a planned change workflow. The urgency usually comes from an approaching range limit or a correctness requirement.

## 5. Investigation Strategy

1. Inventory the column's current definition precisely: exact type, modifiers, nullability, default, identity or generated status.
2. Inventory every dependent object -- indexes on the column, constraints referencing it, incoming foreign keys, views, triggers -- because each must be recreated or revalidated.
3. Measure the table so the rewrite duration, and therefore the lock duration, can be estimated honestly.
4. Classify the change against the rewrite reference to determine whether it is metadata-only or a full rewrite.
5. For a metadata-only change, execute it directly with a lock timeout. For a rewrite, use the online add-and-swap pattern.
6. Validate afterwards that the column has the intended type, that no index was left invalid, and that dependent views still work.

## 6. Prerequisites

- Table ownership; `pg_monitor` for the investigation scripts.
- Certainty about the target type, including precision and scale -- on financial columns this must be confirmed with the owning team, not inferred.
- For a rewrite: enough free storage for a full second copy, and acceptance that the Aurora volume high-water mark will rise permanently.
- For the online pattern: a maintenance window for the final swap only, plus time for the backfill to run online.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_column_definition_inventory.sql`](scripts/01_column_definition_inventory.sql) -- Reads the exact current definition of every column on the target table, including type modifiers, defaults, and identity status.
2. [`scripts/02_dependent_objects_inventory.sql`](scripts/02_dependent_objects_inventory.sql) -- Inventories every index, constraint, incoming foreign key, view, and trigger that depends on the target table.
3. [`scripts/03_target_table_size.sql`](scripts/03_target_table_size.sql) -- Measures the target table so the rewrite duration, and therefore the exclusive lock duration, can be estimated honestly.
4. [`scripts/04_type_change_rewrite_reference.md`](scripts/04_type_change_rewrite_reference.md) -- Reference classification of column type changes into metadata-only and full-rewrite, with the direct-execution runbook for the metadata-only cases.
5. [`scripts/05_online_column_type_change_runbook.md`](scripts/05_online_column_type_change_runbook.md) -- The guarded online add-and-swap runbook for a type change that requires a rewrite, avoiding any long exclusive lock.
6. [`scripts/06_post_change_verification.sql`](scripts/06_post_change_verification.sql) -- Confirms the column now has the intended type and that no index or constraint was left invalid by the change.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- A full table rewrite generates WAL proportional to the entire table, which every Aurora reader applies from the shared storage volume. On a large table expect significant reader lag for the duration and plan for stale customer-facing reads.
- The second copy created by a rewrite permanently raises the Aurora volume high-water mark even after the original is released. Budget for the peak.
- An Aurora failover during a rewrite rolls the whole statement back, since DDL is transactional. Nothing is corrupted, but hours of work are lost -- another argument for the online pattern on large tables.
- The online add-and-swap pattern keeps every step short, which makes it far more resilient to an unplanned Aurora failover than a single multi-hour rewrite.

## 8. Interpretation Guide

- The decisive question is whether the change requires a rewrite. PostgreSQL skips the rewrite only when the new type is binary-coercible from the old one and no constraint needs rechecking.
- Metadata-only, genuinely instant: `varchar(n)` to a *larger* `varchar(m)`, `varchar(n)` to `text`, `numeric(p,s)` to a `numeric` with greater precision and the same scale, and `timestamp` to `timestamptz` *only* when the session `TimeZone` is UTC.
- Full rewrite: `integer` to `bigint`, any *narrowing* change, any numeric scale change, `text` to `varchar(n)`, and almost anything involving a `USING` expression.
- `integer` to `bigint` is the single most common case on an exchange and it always rewrites. There is no shortcut, which is exactly why the online add-and-swap pattern exists and why this change must be started long before the ceiling is reached.
- A rewrite rebuilds every index on the table as well as the heap, so a table with a dozen indexes takes far longer than its heap size alone suggests.
- Every dependent view must be dropped and recreated around a type change, because a view records the type of each output column. Materialized views additionally need repopulating.
- Incoming foreign keys referencing the changed column must have their referencing columns changed to a compatible type too -- and that means a coordinated change across every child table, which is usually the real scope of the work.
- If the column is fed by a sequence that is itself approaching its ceiling, the sequence needs attention as well; changing the column type does not widen the sequence.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If inserts are already failing with an out-of-range error, this is a live outage. The immediate mitigation is usually to reduce write pressure while the emergency change is planned -- there is no fast, safe fix at that point, which is why the change must be started with months of headroom.
- If an `ALTER COLUMN ... TYPE` is currently running and blocking the application, cancel it. A rewrite is fully transactional, so cancellation rolls back cleanly and leaves nothing behind.

**Short-term remediation** (hours to days):

- For a metadata-only change, execute it directly with a lock timeout -- it takes milliseconds.
- For a rewrite on a small or quiet table, execute it in a window with a lock timeout and a second session standing by.
- For a rewrite on a large table, begin the online add-and-swap pattern; the backfill runs for as long as it needs to without any downtime.

**Long-term engineering fix** (days to weeks):

- Use `bigint` for every surrogate key on a high-volume table from the outset. The storage difference is negligible next to the cost of retrofitting it under time pressure.
- Monitor sequence and integer-column headroom proactively so a ceiling is detected with months of runway, not days.
- Use `numeric` with explicit, generous precision for financial amounts and agree the scale at design time with the settlement and compliance teams.
- Standardize on `timestamptz` everywhere so timezone corrections never become a type-change project.

## 10. Production Safety

- All `.sql` scripts here are read-only. Every DDL statement lives in the `.md` runbooks.
- Never run `ALTER COLUMN ... TYPE` on a large production table without first classifying it as metadata-only or rewriting. Getting that wrong is the difference between milliseconds and hours of exclusive lock.
- Always set `lock_timeout`, even for a metadata-only change, so the statement cannot form a lock queue.
- The backfill in the online pattern must be batched and committed in chunks -- never a single `UPDATE` across the whole table, which holds a long-running transaction, blocks vacuum cleanup database-wide, and generates one enormous WAL burst.
- On financial columns, validate the data after any conversion. A scale truncation on an amount column is a silent correctness failure that reconciliation will find later and much more expensively.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- An integer column is within weeks of its ceiling on a table on the trading path -- this is a pending outage and needs immediate prioritization above normal work.
- The change is to a financial amount or price column where precision or scale is affected -- compliance and settlement must sign off before execution.
- Incoming foreign keys from tables owned by other teams must change type in lockstep -- that coordination is the critical path and needs engineering leadership.
- The online pattern's validation step shows any row count or checksum mismatch -- halt immediately and do not cut over with unvalidated financial data.

## 12. Related Issues

- [large-table-ddl](../large-table-ddl/README.md)
- [add-column-large-table](../add-column-large-table/README.md)
- [ddl-lock-investigation](../ddl-lock-investigation/README.md)
- [ddl-blocking](../../concurrency-and-locking/ddl-blocking/README.md)
- [partition-existing-large-table](../../partitioning/partition-existing-large-table/README.md)
- [table-growth](../../storage-and-capacity/table-growth/README.md)
