# 05_test_memory_hypothesis_safely

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `05_test_memory_hypothesis_safely.md` |
| Purpose | Guarded runbook for confirming a hash spill in the plan and testing a larger work_mem without endangering the instance. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Reader instance preferred; writer only when the statement must run there. |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | Step 1: none. Steps 2 and 3: a full execution of the statement, plus the temporary file and memory footprint it implies. A mis-sized work_mem test on a busy writer can itself cause memory pressure. |
| Required privileges | The same privileges the statement under investigation requires. Changing a role's default work_mem additionally requires ALTER ROLE privileges and change-management approval. |
| Prerequisites | Scripts 01-04 completed; a candidate statement with representative parameters identified; the memory arithmetic in step 3 done before running it. |
| Execution order | Step 05 of workflow `query-optimization/hash-join-analysis` |
| Related scripts | ../sort-spills/README.md, ../temp-file-investigation/README.md |

## How to interpret / use this runbook

The deliverable is a decision between 'fix the estimate' and 'grant more memory at the narrowest workable scope'. Read the Batches figure and the estimated-versus-actual gap on the Hash node together: they tell you which of those two it is, and step 4 maps that answer onto the correct remediation and the correct scope.

---

## What this runbook decides

Whether the statement is spilling because memory is too small, or because the
planner's estimate was wrong. Those look identical from the outside and have
completely different fixes.

## Step 1 -- Look at the plan without executing anything

```sql
EXPLAIN (FORMAT TEXT)
SELECT ... ;
```

This shows the join strategy and the estimated row counts on each side. It does not
show batches or memory usage -- those only exist at run time -- but it tells you
which input the planner intends to build the hash from and how large it thinks that
input is. If that estimate is obviously wrong, go fix statistics first and come
back; you may never need step 2.

## Step 2 -- Measure the actual spill

```sql
SET LOCAL statement_timeout = '30s';
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT ... ;
```

This executes the statement. Prefer a reader instance. In the output, find the
`Hash` node:

```
->  Hash  (cost=... rows=1200000 width=48)
      Buckets: 65536  Batches: 16  Memory Usage: 4096kB
```

- `Batches: 1` means no spill.
- `Batches: 16` means the build input was partitioned into 16 pieces and 15 of them
  were written to temporary files and read back.
- `Batches: 16 (originally 4)` means the planner expected 4 and discovered at run
  time that it needed 16 -- a spill **and** proof of an underestimate.
- Compare the `Hash` node's estimated `rows=` against `actual rows` on its input.
  A large gap means the fix is statistics, not memory.

## Step 3 -- Test more memory, for one statement only

```sql
BEGIN;
SET LOCAL work_mem = '256MB';         -- this transaction only
SET LOCAL statement_timeout = '30s';
EXPLAIN (ANALYZE, BUFFERS)
SELECT ... ;
ROLLBACK;
```

- `SET LOCAL` inside an explicit transaction is the safest possible scope: the
  setting dies with the transaction and cannot leak to the connection pool.
- Increase in steps (64MB, 128MB, 256MB) and stop at the smallest value that gets
  `Batches: 1`. The goal is the minimum sufficient allocation, not the largest one
  that fits.
- **Before you run this, do the arithmetic.** Worst-case memory for one statement
  is roughly:

  ```
  work_mem x hash_mem_multiplier x (hash/sort nodes in the plan)
            x (1 + max_parallel_workers_per_gather)
  ```

  Multiply again by how many sessions would run it concurrently in production. On
  a writer serving hundreds of exchange connections, a 256MB work_mem applied
  broadly is an out-of-memory incident waiting to happen.

## Step 4 -- Apply the right fix at the right scope

| Evidence | Fix | Scope |
|---|---|---|
| Estimate wrong, statistics stale | Targeted `ANALYZE` | The affected table |
| Estimate wrong, statistics fresh, correlated columns | `CREATE STATISTICS` on the correlated columns | The affected table |
| Estimate right, input genuinely large, report is analytical | `ALTER ROLE reporting_role SET work_mem = '256MB';` | One role |
| Estimate right, spill on a hot OLTP path | Reduce the input (predicate, index, partition pruning) | The query |
| Spilling reports competing with trading traffic | Move the workload to a dedicated reader with its own parameter group | The cluster topology |

## Never do this

- Do not raise `work_mem` in the Aurora cluster parameter group as a first response.
  Every connection inherits it, and the exposure is multiplied by nodes, workers,
  and concurrency.
- Do not run step 2 or 3 against a data-modifying statement outside
  `BEGIN ... ROLLBACK`.
- Do not tune memory before checking statistics. Fixing an estimate is free and
  permanent; adding memory is neither.
