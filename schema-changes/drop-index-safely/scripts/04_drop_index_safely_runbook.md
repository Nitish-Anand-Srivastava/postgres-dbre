# 04_drop_index_safely_runbook

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `04_drop_index_safely_runbook.md` |
| Purpose | The guarded DDL runbook for dropping an index, including the transaction-rollback rehearsal that proves the drop is safe first. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only (the query reads/writes state that only exists or is meaningful on the writer) |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | Varies by step -- read each step's own warning before executing it. |
| Required privileges | Table owner, or a role granted the `MAINTAIN` privilege on the table (PostgreSQL 16+), or a role with `pg_maintain` membership. DDL variants additionally require the privileges needed for the specific DDL statement (e.g. ownership to ALTER TABLE). |
| Prerequisites | Scripts 01-03 completed, usage evidence gathered across a full business cycle and from every instance in the cluster, and the exact index definition recorded. The read-only investigation scripts for this workflow have been completed and reviewed; a change ticket exists; a second engineer is present; and the rollback path has been agreed before the first statement is executed. |
| Execution order | Step 04 of workflow `schema-changes/drop-index-safely` |
| Related scripts | 03_index_role_and_drop_verdict.sql, 05_post_drop_regression_check.sql |

## How to interpret / use this runbook

Step 2 is the point of this runbook -- everything else is routine. Rehearsing the drop inside a transaction and rolling it back gives you the planner's real answer for the cost of a few seconds, and it is the only technique here that catches the month-end reconciliation query that usage counters never reflected. Keep the rehearsal transaction extremely short and use EXPLAIN without ANALYZE, because the plain DROP INDEX inside it holds an AccessExclusiveLock that blocks reads as well as writes until you roll back. Drop one index at a time with a monitoring gap between each so a regression is attributable. Substitute your real schema, table, index, and query names into every template before running anything.

---

## Step 1 -- record the definition, before anything else

```sql
-- Read-only. Copy the output into the change ticket verbatim. If a regression
-- forces a rebuild, you want a copy-paste, not a reconstruction from memory
-- while a reconciliation job is failing.
SELECT pg_get_indexdef(ix.indexrelid) AS exact_definition
FROM pg_index ix
JOIN pg_class i ON i.oid = ix.indexrelid
JOIN pg_class t ON t.oid = ix.indrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
WHERE n.nspname = 'public'
  AND t.relname = 'trades'
  AND i.relname = 'idx_trades_legacy_lookup';
```

## Step 2 -- rehearse the drop and roll it back

This is the most valuable technique in this workflow and the most underused. `DROP INDEX` (the plain form) is fully transactional, so you can remove the index, ask the planner what it would do without it, and then undo everything.

```sql
BEGIN;
  -- Keep this transaction very short. The plain DROP INDEX takes an
  -- AccessExclusiveLock on the table and holds it until COMMIT or ROLLBACK,
  -- which blocks reads as well as writes for that whole window.
  SET LOCAL lock_timeout = '3s';

  DROP INDEX public.idx_trades_legacy_lookup;

  -- Now ask the planner what it would do WITHOUT the index. Use EXPLAIN only,
  -- never EXPLAIN ANALYZE here -- ANALYZE actually executes the query, which
  -- inside this transaction means running a potentially enormous sequential
  -- scan while holding an AccessExclusiveLock on a production table.
  EXPLAIN SELECT * FROM public.trades
  WHERE account_id = 12345 AND executed_at > now() - interval '30 days';

ROLLBACK;  -- nothing is changed; the index is still there
```

If the plan is still acceptable -- another index covers it, or the remaining plan is a cheap scan on a small partition -- the drop is safe. If it turns into a sequential scan over the whole table, you have just prevented an incident at the cost of thirty seconds.

Repeat for every query you believe might depend on the index, including the month-end and reconciliation queries that are precisely the ones the usage counters fail to reflect.

## Step 3 -- drop it concurrently

```sql
-- Must NOT be inside BEGIN/COMMIT. PostgreSQL rejects it with:
--   ERROR:  DROP INDEX CONCURRENTLY cannot run inside a transaction block
-- Only one index per statement is permitted in the concurrent form.
SET lock_timeout = '5s';
DROP INDEX CONCURRENTLY IF EXISTS public.idx_trades_legacy_lookup;
```

| Property | `DROP INDEX CONCURRENTLY` | `DROP INDEX` (plain) |
|---|---|---|
| Lock level | `ShareUpdateExclusiveLock` | `AccessExclusiveLock` |
| Blocks reads | No | **Yes** |
| Blocks writes | No | **Yes** |
| Inside a transaction block | **Not permitted** | Yes |
| Rollback | None once it proceeds | Clean -- `ROLLBACK` undoes it |
| Production use | **Default** | Rehearsal only (step 2) |

- **Blocking risk:** minimal. Like the concurrent create, it waits for transactions older than its phase boundaries, so a long-running transaction can delay it -- but it blocks nothing itself.
- **Rollback:** none once it proceeds. Recovery is recreating the index concurrently from the definition recorded in step 1, which on a large table takes hours -- which is exactly why step 2 exists.
- **Production considerations:** drop one index at a time with a monitoring gap between each, so any regression can be attributed to a specific drop rather than to a batch of five.

## Step 4 -- constraint-backed indexes

An index backing a primary key or unique constraint cannot be dropped by name; the statement fails. Drop the constraint instead, which removes the index with it:

```sql
BEGIN;
  SET LOCAL lock_timeout = '3s';
  ALTER TABLE public.trades DROP CONSTRAINT trades_external_id_key;
COMMIT;
```

- **Lock level:** `AccessExclusiveLock`, milliseconds -- it is a catalog operation, the index file is removed afterwards.
- **Rollback:** clean while inside the transaction.
- **Production considerations:** dropping a unique constraint removes a correctness guarantee, not just an index. On a financial table this needs explicit sign-off from the owning team and, for deposits, withdrawals, or ledger tables, from compliance.

## Step 5 -- monitor afterwards

Run `05_post_drop_regression_check.sql` immediately and again over the following days, covering at least one full cycle of periodic jobs. A regression from a wrong drop typically appears when a weekly or month-end job runs, not in the first hour.

If a regression appears, recreate the index concurrently from the definition recorded in step 1 and treat it as a normal index build.
