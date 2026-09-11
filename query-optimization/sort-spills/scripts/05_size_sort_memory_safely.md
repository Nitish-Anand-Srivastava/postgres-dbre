# 05_size_sort_memory_safely

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `05_size_sort_memory_safely.md` |
| Purpose | Guarded runbook for confirming a sort spill and choosing between an index, a smaller input, and more memory. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Reader instance preferred for read-only statements. |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | Step 1: none. Steps 2 and 3: a full execution of the statement, including its temporary file I/O. A large work_mem test on a busy instance contributes real memory pressure for the duration. |
| Required privileges | The same privileges the statement under investigation requires. Changing a role default additionally requires ALTER ROLE privileges. |
| Prerequisites | Scripts 01-04 completed and the spilling statement plus representative parameters identified. |
| Execution order | Step 05 of workflow `query-optimization/sort-spills` |
| Related scripts | ../temp-file-investigation/README.md, ../hash-join-analysis/README.md |

## How to interpret / use this runbook

Run step 1 first -- if there is no Sort node, this workflow does not apply. Use step 2 to get the Sort Method and the Disk size, and only use step 3 when the index and query-shape options in step 4 are genuinely unavailable. The deliverable is the narrowest fix that removes the spill, with an index preferred over memory wherever one can supply the ordering.

---

## What this runbook produces

A decision between three remediations, in descending order of preference: remove the
sort with an index, shrink the sort's input, or grant more memory at the narrowest
scope that works.

## Step 1 -- See whether a sort is planned at all (free)

```sql
EXPLAIN (FORMAT TEXT)
SELECT ... ORDER BY ... ;
```

Executes nothing. A `Sort` node means an explicit sort is planned. An `Index Scan`
satisfying the `ORDER BY` with no `Sort` node above it means the ordering is already
free and there is nothing to fix here.

## Step 2 -- Confirm the spill and its size (executes the statement)

```sql
SET LOCAL statement_timeout = '30s';
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT ... ORDER BY ... ;
```

Read the `Sort Method` line:

```
->  Sort  (cost=... rows=2400000 width=96)
      Sort Key: t.executed_at DESC
      Sort Method: external merge  Disk: 412320kB
```

- `quicksort  Memory: NkB` -- fits in memory, nothing to fix.
- `external merge  Disk: NkB` -- spilled. The `Disk` figure is the right order of
  magnitude for the memory the sort needed.
- `top-N heapsort  Memory: NkB` -- a `LIMIT` let PostgreSQL keep only the top N
  rows. This is the cheap case and is what keyset pagination produces.

Also compare the Sort node's estimated `rows=` against `actual rows`: a large gap
means the planner never expected this sort to be big, and the real fix is
statistics, not memory.

Run this on a reader for read-only statements.

## Step 3 -- Find the minimum sufficient work_mem (if memory is the answer)

```sql
BEGIN;
SET LOCAL work_mem = '128MB';        -- this transaction only
SET LOCAL statement_timeout = '30s';
EXPLAIN (ANALYZE, BUFFERS)
SELECT ... ORDER BY ... ;
ROLLBACK;
```

Step the value up (32MB, 64MB, 128MB, 256MB) until `Sort Method` becomes
`quicksort`. Use the **smallest** value that achieves it -- the goal is the minimum
sufficient allocation, not the largest one that fits.

Before applying that value anywhere beyond a single transaction, do the arithmetic:

```
worst case per statement = work_mem x (sort + hash nodes)
                                    x (1 + max_parallel_workers_per_gather)
worst case on the instance = that x concurrent sessions running it
```

## Step 4 -- Apply the fix at the right scope

| Evidence | Fix | Scope |
|---|---|---|
| An index could supply the ordering | `CREATE INDEX CONCURRENTLY` on the sort key | Permanent, all volumes |
| Sort estimate far below actual | Targeted `ANALYZE`, then re-plan | The table |
| Deep `OFFSET` pagination | Keyset pagination in the application | The query |
| Wide rows being sorted | Select fewer columns; sort keys and identifiers only | The query |
| Genuinely large analytical sort | `ALTER ROLE reporting_role SET work_mem = '256MB';` | One role |
| Analytical sorts competing with trading | Dedicated reader with its own parameter group | Cluster topology |

### Keyset pagination, the highest-leverage fix for exchange history endpoints

```sql
-- Instead of: ORDER BY executed_at DESC OFFSET 900000 LIMIT 50
-- (which sorts everything and throws away 900,000 rows)
SELECT ...
FROM trades
WHERE account_id = :account_id
  AND (executed_at, id) < (:last_seen_at, :last_seen_id)
ORDER BY executed_at DESC, id DESC
LIMIT 50;
```

With an index on `(account_id, executed_at DESC, id DESC)` this becomes a bounded
index scan with no sort and no discarded rows, at any page depth.

## Never do this

- Do not raise `work_mem` in the cluster parameter group to fix one report.
- Do not run step 2 or 3 against a data-modifying statement outside
  `BEGIN ... ROLLBACK`.
- Do not treat more memory as a permanent answer to a sort that grows with the
  table: it postpones the problem to the next volume threshold.
