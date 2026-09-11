# 05_confirm_estimate_error

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `05_confirm_estimate_error.md` |
| Purpose | Guarded runbook for measuring estimated versus actual rows and applying the correct statistics remediation. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance preferred; safe to run on a reader but results reflect only that reader's local activity |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | Step 1: none. Step 2: a full execution of the statement. Step 3: ANALYZE reads a sample of the table and takes a SHARE UPDATE EXCLUSIVE lock; ALTER TABLE ... SET STATISTICS takes a brief ACCESS EXCLUSIVE lock; CREATE STATISTICS is catalog-only but makes every subsequent ANALYZE of that table do more work. |
| Required privileges | pg_monitor for the read-only steps. ANALYZE requires table ownership or MAINTAIN; ALTER TABLE and CREATE STATISTICS require table ownership. |
| Prerequisites | Scripts 01-04 completed, with the mis-estimated predicate and its columns identified. |
| Execution order | Step 05 of workflow `query-optimization/cardinality-estimation` |
| Related scripts | ../stale-statistics/README.md, ../nested-loop-problems/README.md |

## How to interpret / use this runbook

Use step 1 to form the hypothesis and step 2 only when you need the actual counts to confirm it. The output of this runbook should be one specific, minimal statistics change -- a targeted ANALYZE, one column's statistics target, or one extended statistics object -- followed by a re-capture proving the estimate moved.

---

## What you are trying to establish

Which node in the plan is being mis-estimated, by how much, and in which direction.
Everything else -- the join strategy, the join order, the index choice -- follows
from that number.

## Step 1 -- Read the estimates for free

```sql
EXPLAIN (FORMAT TEXT)
SELECT ... ;
```

Executes nothing. Note the estimated `rows=` at each node, especially at the
filter or index scan that feeds the join. If you already know from the application
that the filter matches millions of rows and the planner says 12, you have your
answer without running anything.

## Step 2 -- Get the actual counts (executes the statement)

```sql
SET LOCAL statement_timeout = '20s';
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT ... ;
```

Compare `rows=` with `actual rows=` at every node and find the **deepest** node
where they diverge by an order of magnitude. That node is the cause; every bad
decision above it is a consequence. Remember that on the inner side of a nested
loop, `actual rows` is per loop -- multiply by `loops`.

Prefer a reader instance for read-only statements. For a write statement, wrap in
`BEGIN ... ROLLBACK` and do not do it on wallet, ledger, or settlement tables
during trading hours.

A cheaper alternative for a single predicate, which does not run the full query:

```sql
-- What the planner thinks:
EXPLAIN SELECT 1 FROM orders WHERE market_symbol = 'BTC-USD' AND status = 'open';
-- What is actually true (a plain count, no EXPLAIN ANALYZE of the full query):
SELECT count(*) FROM orders WHERE market_symbol = 'BTC-USD' AND status = 'open';
```

The count still scans, so bound it with `statement_timeout` too, but it isolates
the predicate without executing the rest of the query.

## Step 3 -- Map the error to the right remediation

| What the statistics show | Remediation |
|---|---|
| `last_analyze` stale, high `n_mod_since_analyze` | `ANALYZE schema.table;` -- targeted, change-managed |
| Skewed column, `mcv_entries` pinned at the target | `ALTER TABLE t ALTER COLUMN c SET STATISTICS 1000;` then `ANALYZE t;` |
| Two columns filtered together, estimate = product of selectivities | `CREATE STATISTICS ... (dependencies, mcv) ON a, b FROM t;` then `ANALYZE t;` |
| Predicate wraps a column in a function or cast | Expression index, or `CREATE STATISTICS ... ON (expr) FROM t;` |
| `n_distinct` badly wrong on a huge table | `ALTER TABLE t ALTER COLUMN c SET (n_distinct = -0.3);` then `ANALYZE t;` |

### The statements themselves, with their real costs

```sql
-- Targeted statistics refresh. Takes a SHARE UPDATE EXCLUSIVE lock: does not
-- block reads or writes, but does conflict with another ANALYZE/VACUUM and with
-- most ALTER TABLE forms on the same table. Reads a sample of the table, so on a
-- very large table it is real I/O -- prefer off-peak for multi-hundred-GB tables.
ANALYZE public.orders;

-- Higher resolution for one skewed column. The ALTER is instant (catalog only),
-- but it takes ACCESS EXCLUSIVE briefly, and it has NO effect until the
-- following ANALYZE actually collects the extra detail.
ALTER TABLE public.orders ALTER COLUMN market_symbol SET STATISTICS 1000;
ANALYZE public.orders;

-- Teach the planner that two columns are related. Creating the object is cheap;
-- it is inert until ANALYZE populates it.
CREATE STATISTICS orders_market_status_stx (dependencies, mcv)
    ON market_symbol, status
    FROM public.orders;
ANALYZE public.orders;
```

Every one of these is a change-managed action on a production exchange database:
raise a change record, run it with a second engineer, and re-capture the plan
afterwards to prove the estimate improved.

## Step 4 -- Verify

Re-run step 1. The estimate at the previously wrong node should now be within the
same order of magnitude as reality, and the plan shape should have changed if the
error was what drove the bad choice. If the estimate improved but the plan did not
change, the estimate was not the binding constraint -- go back to
`analyze-query-plan` and look elsewhere.

## Never do this

- Do not raise `default_statistics_target` cluster-wide to fix one column. Every
  ANALYZE across the database gets slower and every planning cycle gets more
  expensive.
- Do not run a bare database-wide `ANALYZE;` on a production exchange cluster as a
  routine fix. Target the specific tables.
- Do not create extended statistics on every column pair speculatively: each object
  adds work to every ANALYZE of that table.
