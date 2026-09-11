# 06_validate_index_change_safely

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `06_validate_index_change_safely.md` |
| Purpose | Guarded runbook for validating an index addition or removal before applying it to a hot exchange table. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only -- index DDL cannot run on a reader. |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | CREATE INDEX CONCURRENTLY and DROP INDEX CONCURRENTLY take SHARE UPDATE EXCLUSIVE rather than ACCESS EXCLUSIVE, so reads and writes continue, but the build is I/O intensive, takes roughly twice as long as a plain build, and conflicts with vacuum and other DDL on the same table. |
| Required privileges | Table ownership to create or drop an index. pg_monitor is sufficient for the validation steps. |
| Prerequisites | Scripts 01-05 completed, the candidate index identified, and for a removal, confirmation across every instance and a full business cycle. |
| Execution order | Step 06 of workflow `query-optimization/inefficient-index-usage` |
| Related scripts | ../../tables-and-indexes/unused-indexes/README.md, ../../tables-and-indexes/missing-index-candidates/README.md |

## How to interpret / use this runbook

Use part A when the evidence points at a missing or badly shaped index, and part B when it points at an index that costs more than it returns. Both parts end with a verification step, and part B's B2 is the non-negotiable one: the recorded definition is the whole rollback plan for an index removal.

---

## Principle

An index change on `orders`, `trades`, `wallets`, or `ledger_entries` affects every
write on the exchange's critical path. Validate first, change once, and always use
the `CONCURRENTLY` forms.

## Part A -- Validating a proposed NEW index

### A1. Confirm the planner is not already using an equivalent index (free)

```sql
EXPLAIN (FORMAT TEXT)
SELECT ... WHERE ... ;
```

Executes nothing. If it already shows an `Index Scan` on a suitable index, the
problem is elsewhere and a new index is not the answer.

### A2. Check whether the predicate is sargable at all

A predicate that wraps the column in a function or a cast cannot use an ordinary
index on that column:

```sql
-- Cannot use an index on created_at:
WHERE date(created_at) = '2026-09-11'
-- Can:
WHERE created_at >= '2026-09-11' AND created_at < '2026-09-12'

-- Cannot use an index on account_id if the types differ:
WHERE account_id::text = :param
-- Can, when the parameter is passed with the column's own type:
WHERE account_id = :param
```

Rewriting the predicate is free and permanent; adding an index to work around an
unnecessary cast is not.

### A3. Build it CONCURRENTLY

```sql
-- Takes SHARE UPDATE EXCLUSIVE, not ACCESS EXCLUSIVE: reads and writes continue.
-- Cannot run inside a transaction block. Takes roughly twice as long as a plain
-- build and needs space for the finished index on the cluster volume.
CREATE INDEX CONCURRENTLY idx_trades_account_executed
    ON public.trades (account_id, executed_at DESC);
```

If the build is interrupted -- a cancelled session, a `statement_timeout`, a
deadlock -- it leaves an **INVALID** index behind. Check for one afterwards with
script 05 of this workflow, and drop it before retrying; an invalid index cannot be
validated in place.

### A4. Prove it is being used

```sql
EXPLAIN (FORMAT TEXT) SELECT ... ;    -- should now show the new index
```

Then re-run script 01 after a period of production traffic and confirm `idx_scan`
is climbing. An index that is still unused after a day of traffic is a failed
hypothesis: drop it rather than leaving it to tax every write.

## Part B -- Validating a proposed index REMOVAL

### B1. Confirm it is genuinely unused, everywhere

- `idx_scan = 0` **and** `last_idx_scan IS NULL` (or very old) in script 01.
- Verified on the writer **and on every reader** -- reporting queries run there and
  their index usage is counted separately.
- Instance uptime and `stats_reset` confirm the counters cover a meaningful period.
- At least one full business cycle has elapsed, including month-end and
  quarter-end reconciliation and any annual audit extract.
- It backs no primary key, unique, exclusion, or foreign key constraint.

### B2. Record the definition before you drop it

```sql
SELECT pg_get_indexdef(i.oid)
FROM pg_class i
JOIN pg_namespace n ON n.oid = i.relnamespace
WHERE n.nspname = 'public' AND i.relname = 'idx_candidate_for_removal';
```

Paste the result into the change record. That one line is the entire rollback plan.

### B3. Drop it CONCURRENTLY

```sql
-- Avoids the ACCESS EXCLUSIVE lock that a plain DROP INDEX takes.
-- Cannot run inside a transaction block.
DROP INDEX CONCURRENTLY public.idx_candidate_for_removal;
```

### B4. Watch for the regression

For the next full business cycle, watch the sequential scan counters on that table
(script 05) and the latency of the queries that touched those columns. If something
regresses, recreate the index from the definition recorded in B2 using
`CREATE INDEX CONCURRENTLY`.

## Never do this

- Never `CREATE INDEX` or `DROP INDEX` without `CONCURRENTLY` on a hot exchange
  table: both take `ACCESS EXCLUSIVE` and block every read and write for the
  duration.
- Never drop an index because `idx_scan = 0` on one instance at one point in time.
- Never drop a constraint-backing index to save space; drop the constraint if the
  constraint is genuinely not needed, which is a different and larger decision.
- Never add an index to compensate for a predicate that could simply be rewritten
  to be sargable.
