# 04_add_column_semantics_reference

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `04_add_column_semantics_reference.md` |
| Purpose | Reference classification of every ADD COLUMN form by rewrite behavior, with the reasoning behind the PostgreSQL fast-default optimization. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only (the query reads/writes state that only exists or is meaningful on the writer) |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | None by itself -- this is a reference document. The statements it classifies have the impacts described per row. |
| Required privileges | Table owner, or a role granted the `MAINTAIN` privilege on the table (PostgreSQL 16+), or a role with `pg_maintain` membership. DDL variants additionally require the privileges needed for the specific DDL statement (e.g. ownership to ALTER TABLE). |
| Prerequisites | Scripts 01-03 completed so the table size, existing columns, and lock state are known. |
| Execution order | Step 04 of workflow `schema-changes/add-column-large-table` |
| Related scripts | 05_add_column_execution_runbook.md |

## How to interpret / use this runbook

Classify the exact statement text here before it reaches a change ticket, because the difference between the safe form and the rewriting form is a single expression in the default clause and is invisible to anyone skim-reading the migration. The practical rule for a large table is short: constant defaults only, never a volatile default, never GENERATED ... STORED, and never an identity column added to a populated table. Where the requirement genuinely needs a per-row value, the runbook in script 05 shows how to get it with a constant default plus a batched online backfill instead.

---

## Which forms rewrite the table

| Statement form | Rewrites? | Lock hold | Notes |
|---|---|---|---|
| `ADD COLUMN c type` | **No** | Milliseconds | Nullable, no default -- always cheap |
| `ADD COLUMN c type DEFAULT <constant>` | **No** (PG11+) | Milliseconds | Default stored once in `pg_attribute`, materialized lazily |
| `ADD COLUMN c type NOT NULL DEFAULT <constant>` | **No** (PG11+) | Milliseconds | The constant default satisfies `NOT NULL` for existing rows |
| `ADD COLUMN c type NOT NULL` (no default) | Fails | n/a | Rejected outright if the table has any rows |
| `ADD COLUMN c type DEFAULT now()` | **Yes** | Whole rewrite | Volatile -- must be evaluated per row |
| `ADD COLUMN c type DEFAULT gen_random_uuid()` | **Yes** | Whole rewrite | Volatile, and each row needs a distinct value |
| `ADD COLUMN c type GENERATED ALWAYS AS (...) STORED` | **Yes** | Whole rewrite | Value must be computed and stored for every existing row |
| `ADD COLUMN c type GENERATED ... AS IDENTITY` | **Yes** | Whole rewrite | Every existing row needs a distinct identity value |
| `ADD COLUMN c type REFERENCES other(id)` | No rewrite, but scans | Scan duration | Validates every existing row; use the `NOT VALID` two-step instead |

## Why the fast path works

Before PostgreSQL 11, adding a column with a default meant writing the value into every existing row -- a full rewrite. From PostgreSQL 11, a **constant** default is stored once in the `pg_attribute` catalog row for that column (`atthasmissing = true`, value in `attmissingval`). When a query reads a row written before the column existed, PostgreSQL substitutes that stored value transparently. Existing rows are never touched; they acquire a real physical value only if and when they are updated for some other reason.

This means:

- The statement is O(1) in table size. A 5 GB table and a 5 TB table take the same few milliseconds.
- There is no read penalty afterwards -- the substitution is part of normal tuple deforming.
- You can verify the optimization was used by checking `atthasmissing` in `06_post_change_verification.sql`, rather than assuming it.

The optimization applies only to a **constant** default. `now()` is not constant (each row conceptually gets its own evaluation), so it falls back to the rewrite path -- and the statement text gives no hint that it has done so, which is why this classification must happen at review time.

## `DROP COLUMN` for comparison

`DROP COLUMN` is also catalog-only: the column is marked dropped and its data is ignored, but the bytes stay in every existing row until that row is rewritten for another reason. Storage is therefore reclaimed gradually by vacuum, not immediately -- do not expect a size drop after dropping a wide column from a large table.

- **Lock level:** `AccessExclusiveLock`, milliseconds.
- **Blocking risk:** near zero with a lock timeout.
- **Rollback:** clean, but be aware that any dependent view or index on the column is dropped with it and `CASCADE` will silently take more than you expect -- check `large-table-ddl` script 02 first.
