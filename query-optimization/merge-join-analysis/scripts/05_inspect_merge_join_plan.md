# 05_inspect_merge_join_plan

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `05_inspect_merge_join_plan.md` |
| Purpose | Guarded runbook for reading a merge join plan and deciding between adding an index and adding memory. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Reader instance preferred for read-only statements. |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | Step 1: none. Steps 2 and 4: a full execution of the statement, including any temporary file usage its sorts require. |
| Required privileges | The same privileges the statement under investigation requires; creating the remediation index additionally requires table ownership. |
| Prerequisites | Scripts 01-04 completed and the join's tables, columns, and representative parameters identified. |
| Execution order | Step 05 of workflow `query-optimization/merge-join-analysis` |
| Related scripts | ../sort-spills/README.md, ../../schema-changes/concurrent-index-build/README.md |

## How to interpret / use this runbook

Start with step 1: the presence or absence of Sort nodes above the join inputs answers most of the question at zero cost. Execute the statement only when you need the Sort Method line to distinguish an in-memory sort from a spilling one, and prefer the index fix over the memory fix whenever an index can supply the ordering.

---

## The question this runbook answers

Is this merge join streaming two already-sorted inputs (good, leave it alone), or
is it sorting them first (fixable, usually with one index)?

## Step 1 -- Plan only, no execution

```sql
EXPLAIN (FORMAT TEXT)
SELECT ... ;
```

Nothing is executed. Look at what feeds the `Merge Join`:

```
Merge Join
  Merge Cond: (t.order_id = f.order_id)
  ->  Index Scan using trades_order_id_idx on trades t        <- good: pre-sorted
  ->  Sort                                                    <- costly: must sort
        Sort Key: f.order_id
        ->  Seq Scan on order_fills f
```

Two `Index Scan` inputs and no `Sort` nodes is the efficient case and needs no
further work. Any `Sort` node feeding the join is the target of this
investigation.

## Step 2 -- Measure the sorts (executes the statement)

```sql
SET LOCAL statement_timeout = '30s';
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT ... ;
```

Read `Sort Method` on each Sort node:

- `quicksort  Memory: 8192kB` -- fully in memory. If the sort is small, the merge
  join may still be the best available plan and there is nothing to fix.
- `external merge  Disk: 412MB` -- spilled to a temporary file on local instance
  storage. This sort now dominates the query cost.
- `Incremental Sort` with `Pre-sorted Groups:` -- an index already supplies part of
  the ordering. Extending that index to cover the full sort key usually removes
  the sort entirely, and is the cheapest fix available.

Prefer a reader instance for this capture when the statement is read-only.

## Step 3 -- Choose between an index and memory

| Observation | Fix |
|---|---|
| Sort feeding one side, and a matching index could exist | Create the index on the join key, `CONCURRENTLY`; this removes the sort permanently |
| `Incremental Sort` present | Extend the existing index to cover the remaining sort columns |
| Sort is small and in memory | Leave it; the merge join is fine |
| Sort is unavoidable and spilling | Raise `work_mem` for the batch role only, and reduce the input with better predicates |
| Index exists but is not used for ordering | Check sort direction, `NULLS FIRST/LAST`, leading column order, and join key type/collation mismatches |

An index is almost always the better answer than memory here: it fixes the problem
for every future execution, on every instance, at every data volume, whereas more
memory only postpones the spill until the table grows again.

## Step 4 -- Diagnostic comparison, if you need it

```sql
BEGIN;
SET LOCAL enable_mergejoin = off;    -- diagnostic only, this transaction only
SET LOCAL statement_timeout = '30s';
EXPLAIN (ANALYZE, BUFFERS)
SELECT ... ;
ROLLBACK;
```

This shows what the planner would do instead (usually a hash join) and whether it
is actually faster. It is evidence for the ticket, never a production setting.

## Never do this

- Do not disable `enable_mergejoin` or `enable_sort` outside a single diagnostic
  transaction, and never in the Aurora parameter group.
- Do not build the new index without `CONCURRENTLY` on a hot exchange table: a
  plain `CREATE INDEX` holds a lock that blocks every write to that table for the
  whole build.
- Do not run step 2 or 4 against a data-modifying statement outside
  `BEGIN ... ROLLBACK`.
