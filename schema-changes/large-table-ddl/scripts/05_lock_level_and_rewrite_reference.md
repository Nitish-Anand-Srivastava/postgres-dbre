# 05_lock_level_and_rewrite_reference

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `05_lock_level_and_rewrite_reference.md` |
| Purpose | Reference classification of every common ALTER TABLE variant by lock level, rewrite behavior, table scan, and safe alternative. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only (the query reads/writes state that only exists or is meaningful on the writer) |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | None by itself -- this is a reference document. The statements it classifies have the impacts described per row. |
| Required privileges | Table owner, or a role granted the `MAINTAIN` privilege on the table (PostgreSQL 16+), or a role with `pg_maintain` membership. DDL variants additionally require the privileges needed for the specific DDL statement (e.g. ownership to ALTER TABLE). |
| Prerequisites | Scripts 01-04 completed so the table's size, dependencies, and current lock state are known. |
| Execution order | Step 05 of workflow `schema-changes/large-table-ddl` |
| Related scripts | 06_large_table_ddl_execution_runbook.md |

## How to interpret / use this runbook

Classify the intended statement here before writing the change ticket, and record the lock level and rewrite answer in the ticket itself -- that classification, not the statement text, is what a reviewer needs to approve or reject the change. If the statement lands in the full-rewrite section and the table is large, stop: do not look for a way to make the rewrite faster, switch to the build-alongside-and-swap pattern in script 06. If it lands in the scan-without-rewrite section, always take the two-step alternative; there is no situation on a production exchange table where the one-step form is preferable.

---

## How to use this reference

Find your intended statement below and read three things: the **lock level**, whether it **rewrites** the table, and whether it **scans** the table. Those three facts determine everything about how risky the change is.

The key distinction is duration of lock hold:

- A statement that takes `AccessExclusiveLock` but neither rewrites nor scans holds it for **milliseconds**. With a lock timeout, that is safe on any table at any time.
- A statement that **rewrites** holds `AccessExclusiveLock` for the entire rewrite. On a large table that is an outage.
- A statement that **scans** holds its lock for the scan. Whether that is acceptable depends entirely on which lock level it holds while scanning.

---

## Metadata-only: `AccessExclusiveLock`, no rewrite, no scan

These hold the strong lock only for as long as the catalog update takes -- typically milliseconds. Safe with a lock timeout even on a very large table.

| Statement | Notes |
|---|---|
| `ALTER TABLE ... RENAME TO ...` | Pure catalog change |
| `ALTER TABLE ... RENAME COLUMN ... TO ...` | Breaks application queries referencing the old name -- coordinate the deploy |
| `ALTER TABLE ... ADD COLUMN ... ` (no default, or a constant default on PG11+) | See add-column-large-table |
| `ALTER TABLE ... DROP COLUMN ...` | Marks the column dropped; space is reclaimed lazily by vacuum, not immediately |
| `ALTER TABLE ... ALTER COLUMN ... DROP NOT NULL` | Catalog only |
| `ALTER TABLE ... ALTER COLUMN ... SET DEFAULT` / `DROP DEFAULT` | Affects future rows only |
| `ALTER TABLE ... SET (fillfactor = ...)` | Applies to future page writes only |
| `ALTER TABLE ... ADD CONSTRAINT ... CHECK (...) NOT VALID` | Existing rows are not checked -- this is the cheap half of the two-step pattern |
| `ALTER TABLE ... ADD CONSTRAINT ... FOREIGN KEY ... NOT VALID` | Same, for foreign keys |

## Full rewrite: `AccessExclusiveLock` held for the whole rewrite

**Not acceptable on a large production table during trading hours.** Use the build-alongside-and-swap pattern in script 06 instead.

| Statement | Notes |
|---|---|
| `ALTER TABLE ... ALTER COLUMN ... TYPE ...` (most type changes) | Rewrites heap and every index; see column-type-change for the exceptions |
| `ALTER TABLE ... ADD COLUMN ... DEFAULT <volatile expression>` | A volatile default such as `now()` or `gen_random_uuid()` forces a rewrite; a constant does not on PG11+ |
| `ALTER TABLE ... ADD COLUMN ... GENERATED ALWAYS AS (...) STORED` | Must compute and store the value for every existing row |
| `ALTER TABLE ... SET TABLESPACE ...` | Physically relocates the relation |
| `VACUUM FULL` / `CLUSTER` | Full rewrite plus index rebuild; never on a production exchange table |

## Scan without rewrite: `AccessExclusiveLock` held for the scan

Cheaper than a rewrite but still holds the strong lock while reading every row. Prefer the two-step alternative in every case.

| Statement | Safe alternative |
|---|---|
| `ALTER TABLE ... ADD CONSTRAINT ... CHECK (...)` | Add `NOT VALID`, then `VALIDATE CONSTRAINT` |
| `ALTER TABLE ... ADD CONSTRAINT ... FOREIGN KEY ...` | Add `NOT VALID`, then `VALIDATE CONSTRAINT` |
| `ALTER TABLE ... ALTER COLUMN ... SET NOT NULL` | Add a `CHECK (col IS NOT NULL) NOT VALID`, validate it, then `SET NOT NULL` -- PostgreSQL 12+ uses the validated check to skip the scan |

## Non-blocking: `ShareUpdateExclusiveLock`

These do not block reads or writes. They do block other DDL and autovacuum on the same table.

| Statement | Notes |
|---|---|
| `CREATE INDEX CONCURRENTLY` | Cannot run in a transaction block |
| `DROP INDEX CONCURRENTLY` | Cannot run in a transaction block; one index per statement |
| `REINDEX INDEX CONCURRENTLY` | Needs space for a second copy of the index |
| `ALTER TABLE ... VALIDATE CONSTRAINT ...` | The safe half of the two-step pattern -- scans without blocking |
| `ALTER TABLE ... ALTER COLUMN ... SET STATISTICS ...` | Catalog only; run `ANALYZE` afterwards to take effect |
| `ALTER TABLE ... SET (autovacuum_* = ...)` | Per-table autovacuum tuning |

## Write-blocking: `ShareRowExclusiveLock`

| Statement | Notes |
|---|---|
| `CREATE TRIGGER` | Blocks writes briefly; reads continue |
| `ALTER TABLE ... ADD CONSTRAINT ... EXCLUDE ...` | Also builds an index |

---

## Partitioned tables

DDL on a partitioned parent generally recurses into every partition and acquires locks on all of them in one transaction. On a table with hundreds of partitions the blast radius is the whole dataset at once. Always ask whether the change can be applied partition by partition instead, and prefer `ONLY` plus per-partition execution where the semantics allow it.
