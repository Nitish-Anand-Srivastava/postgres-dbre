# 06_confirm_nested_loop_safely

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `06_confirm_nested_loop_safely.md` |
| Purpose | Guarded runbook for confirming a runaway nested loop with a real plan, and for testing the alternative plan safely. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Reader instance preferred for read-only statements; writer only when unavoidable. |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | Step 1: none. Step 2: a full execution of the statement under investigation, bounded by statement_timeout. Step 3: the same, plus a session-scoped planner change confined to one transaction. |
| Required privileges | The same privileges the statement under investigation requires. |
| Prerequisites | Scripts 01-05 completed and a candidate statement with representative parameters identified. |
| Execution order | Step 06 of workflow `query-optimization/nested-loop-problems` |
| Related scripts | ../cardinality-estimation/README.md, ../hash-join-analysis/README.md |

## How to interpret / use this runbook

Use step 1 alone whenever it is sufficient -- an obviously wrong outer estimate is diagnostic on its own and costs nothing to obtain. Escalate to step 2 only when you need the real loop count, and treat step 3 strictly as evidence-gathering: the deliverable from this runbook is a statistics or index change, never a disabled join method.

---

## Before you run anything

The statement you are about to analyze is, by hypothesis, the one saturating the
instance. `EXPLAIN ANALYZE` executes it in full, so running it carelessly repeats
the incident on purpose. Every command below is deliberate.

## Step 1 -- Confirm the plan shape for free

```sql
EXPLAIN (FORMAT TEXT)
SELECT ... ;                     -- with representative parameter values
```

This executes nothing. Look for `Nested Loop` with a large table on the inner side,
and read the estimated `rows=` on the outer side. If the outer estimate is small
(single or double digits) while you know the real filter matches millions of rows,
you have already found the problem and may not need to execute anything at all.

## Step 2 -- Measure the real loop count, with a hard time bound

```sql
SET LOCAL statement_timeout = '15s';
EXPLAIN (ANALYZE, BUFFERS, TIMING, FORMAT TEXT)
SELECT ... ;
```

- Run this on a **reader instance** if the statement is read-only. The data is the
  same and the writer's order-matching path is untouched.
- The `statement_timeout` is not optional. A runaway loop that ran for 40 minutes
  in production will run for 40 minutes here too, and the timeout is what stops
  the diagnosis from becoming the next incident.
- If the statement times out, that is itself a result: the loop is confirmed
  expensive. Re-run with more selective parameters to get a completable plan.

In the output, on the inner node of the `Nested Loop`, read:

```
->  Index Scan using ... (cost=... rows=1 width=...)
      (actual time=0.004..0.006 rows=1 loops=2841193)
```

`rows` is **per loop**. The real work is `rows x loops`. A `loops` value in the
millions confirms the runaway loop immediately.

## Step 3 -- Prove the alternative plan is better (diagnostic only)

```sql
BEGIN;
SET LOCAL enable_nestloop = off;      -- SESSION-SCOPED, diagnostic only
SET LOCAL statement_timeout = '15s';
EXPLAIN (ANALYZE, BUFFERS)
SELECT ... ;
ROLLBACK;
```

- `SET LOCAL` confines the change to this transaction, and the `ROLLBACK` ends it.
  Nothing leaks into other sessions.
- If the hash-join plan is dramatically faster, you have evidence -- **not a fix**.
  Disabling a join method is never the production remediation: it distorts every
  other query on the connection and will eventually produce a worse plan
  elsewhere.
- The real fix is to make the planner choose that plan on its own, by correcting
  the estimate (ANALYZE, higher statistics target, extended statistics) or by
  adding the index that makes the loop genuinely cheap.

## Step 4 -- Decide the remediation

| Finding in the plan | Correct remediation |
|---|---|
| Outer estimate far below actual, statistics stale | Targeted `ANALYZE` on that table |
| Outer estimate far below actual, statistics fresh, correlated predicates | Extended statistics (`CREATE STATISTICS`) on the correlated columns |
| Inner side doing a sequential scan per loop | Index on the inner join key, built `CONCURRENTLY` |
| Inner index exists but is unused | Check for a type mismatch or a function wrapped around the join column |
| Estimates correct, loop count genuinely huge | Query shape must change -- application-side fix or a materialized intermediate result |

## Never do this

- Do not set `enable_nestloop = off` in the Aurora parameter group. It is a
  diagnostic switch, not a configuration setting, and a cluster-wide change would
  degrade the high-frequency OLTP lookups that legitimately depend on nested loops.
- Do not run step 2 or 3 against a data-modifying statement without wrapping it in
  `BEGIN ... ROLLBACK`, and do not do it at all against `wallets`, `ledger_entries`,
  or settlement tables during trading hours.
