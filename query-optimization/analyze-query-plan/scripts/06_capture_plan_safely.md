# 06_capture_plan_safely

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `06_capture_plan_safely.md` |
| Purpose | Guarded runbook for capturing a query plan: EXPLAIN first, EXPLAIN ANALYZE only under explicit production guardrails. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Reader instance preferred for read-only statements; writer only when the statement itself must run on the writer. |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | Mode 1 has no impact. Mode 2 consumes the same resources as one full execution of the statement. Mode 3 additionally takes row locks, generates WAL, and creates dead tuples even though the change is rolled back. |
| Required privileges | The same privileges the statement under investigation requires. No elevated privileges beyond that. |
| Prerequisites | Scripts 01-05 completed, the target statement and representative parameter values identified, and a decision made about which instance to capture on. |
| Execution order | Step 06 of workflow `query-optimization/analyze-query-plan` |
| Related scripts | ../query-plan-regression/README.md, ../cardinality-estimation/README.md |

## How to interpret / use this runbook

Work down the three capture modes and stop at the least risky one that answers your question -- most plan problems are fully diagnosable from the plan-only capture plus the statistics evidence from script 05. Only escalate to EXPLAIN ANALYZE when you specifically need estimated-versus-actual row counts or real buffer numbers, and only ever wrap a write statement in an explicit transaction that ends in ROLLBACK.

---

## Why this step is a runbook and not a script

Capturing a plan means running something against production. `EXPLAIN` is harmless;
`EXPLAIN ANALYZE` is not, because it **actually executes the statement**. A toolkit
script cannot know whether the statement under investigation is a read of the trade
history or an `UPDATE` on the wallet ledger, so the decision stays with the
operator. Read this whole file before running anything.

## The three capture modes, in increasing order of risk

### 1. Plan only -- always safe

```sql
EXPLAIN (FORMAT TEXT)
SELECT ... ;                      -- the statement under investigation
```

- Does **not** execute the statement. Safe against `SELECT`, `INSERT`, `UPDATE`,
  `DELETE` alike, on the writer, at peak trading hours.
- Shows the chosen plan shape, the estimated row counts, and the cost estimates.
- This is enough to answer most questions: which join strategy, which index, in
  what order. Start here, always.
- Add `VERBOSE` for output column lists and `COSTS OFF` if you want a stable plan
  shape to store as a baseline for later comparison.

### 2. Plan plus real measurements -- executes the statement

```sql
SET LOCAL statement_timeout = '10s';   -- bound the blast radius first
EXPLAIN (ANALYZE, BUFFERS, TIMING, FORMAT TEXT)
SELECT ... ;
```

- **This runs the query for real.** It will take at least as long as the original
  slow execution, and slightly longer because of instrumentation overhead.
- Set `statement_timeout` first, in the same session, so a pathological plan cannot
  itself become the next incident.
- Prefer a reader instance for read-only statements: the data is the same and the
  writer's order-matching path stays untouched. Expect buffer hit counts to differ
  from the writer's, because each instance has its own cache.
- `BUFFERS` is the highest-value option on Aurora: shared read counts are storage
  round trips, which is where the latency actually comes from.
- On PostgreSQL 17 you can add `SERIALIZE` to measure the cost of converting rows
  to wire format, which matters for statements returning very large result sets
  (a full order-book snapshot, a bulk trade export).

### 3. Plan plus real measurements for a write statement -- highest risk

```sql
BEGIN;
SET LOCAL statement_timeout = '10s';
EXPLAIN (ANALYZE, BUFFERS)
UPDATE ... ;                      -- the write statement under investigation
ROLLBACK;                          -- MANDATORY: without this, the write is permanent
```

- The statement is genuinely executed inside the transaction. It takes every row
  lock the real statement would take, generates the same WAL, fires the same
  triggers, and blocks concurrent writers on those rows for its whole duration.
- `ROLLBACK` undoes the data change. It does **not** undo the lock contention, the
  WAL generated, the dead tuples created, or the replica lag caused while it ran.
- Do not do this against `orders`, `wallets`, `ledger_entries`, or any settlement
  table during trading hours. Use a restored snapshot or a pre-production clone
  with representative data volume instead.

## Choosing parameters for the capture

pg_stat_statements normalizes literals to `$1`, `$2`, so the statement text it
stores is not directly runnable. Substitute **representative** values, and note
that for a parameter-sensitive statement there are two interesting captures:

- typical parameters (an average account, a mid-liquidity trading pair), and
- the outlier parameters that produced the `max_exec_time` seen in script 02 (the
  largest institutional account, the single most active pair, the widest date
  range).

A plan captured only with typical values will often look perfectly reasonable while
the real production pain comes entirely from the outliers.

## Reading what you captured

1. Find the deepest node where `rows=` (estimate) and `actual rows=` differ by an
   order of magnitude or more. That node is the cause; everything above it is a
   consequence of the planner believing that number.
2. Multiply `actual rows` by `loops` for any node on the inner side of a nested
   loop -- the per-loop figure hides the real total work.
3. Look for `Sort Method: external merge  Disk: NkB` (a sort spill) and for
   `Batches: N  Memory Usage: MkB` with N greater than 1 on a Hash node (a hash
   spill). Both mean `work_mem` was insufficient for that node.
4. Look for `Seq Scan` on a large table where an index scan was expected, and for
   `Rows Removed by Filter` far exceeding the rows returned -- both point at a
   missing or unusable index.
5. Compare `shared hit` against `shared read`: a high read count on Aurora is
   storage traffic and translates directly into latency.

## Record the result

Save the plan text, the exact parameter values used, the instance it was captured
on, and the timestamp, alongside the queryid from script 01. That record is what
makes the `query-plan-regression` workflow possible later; without it, a future
'this got slower' report has nothing to compare against.
