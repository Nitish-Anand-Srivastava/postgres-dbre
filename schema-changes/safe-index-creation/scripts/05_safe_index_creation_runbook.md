# 05_safe_index_creation_runbook

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `05_safe_index_creation_runbook.md` |
| Purpose | The guarded DDL runbook for creating an index, documenting lock level, blocking risk, transaction behavior, rollback, and production considerations for each method. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only (the query reads/writes state that only exists or is meaningful on the writer) |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | Varies by step -- read each step's own warning before executing it. |
| Required privileges | Table owner, or a role granted the `MAINTAIN` privilege on the table (PostgreSQL 16+), or a role with `pg_maintain` membership. DDL variants additionally require the privileges needed for the specific DDL statement (e.g. ownership to ALTER TABLE). |
| Prerequisites | The read-only investigation scripts for this workflow have been completed and reviewed; a change ticket exists; a second engineer is present; and the rollback path has been agreed before the first statement is executed. |
| Execution order | Step 05 of workflow `schema-changes/safe-index-creation` |
| Related scripts | 06_post_build_validation.sql |

## How to interpret / use this runbook

Pick the method from the comparison table first and write the choice into the change ticket with its justification, because that decision -- not the index definition -- is what determines whether this change is routine or an incident. Method A is the production default on a trading platform; Method B is only for tables genuinely not being written to; Method C is mandatory for partitioned tables regardless of size. Substitute your real schema, table, index name, and column list into the template before running anything, and execute the statements one at a time with the output of each checked before the next.

---

## Choosing a method

| | Plain `CREATE INDEX` | `CREATE INDEX CONCURRENTLY` |
|---|---|---|
| Lock level | `ShareLock` on the table | `ShareUpdateExclusiveLock` on the table |
| Blocks reads | No | No |
| Blocks writes | **Yes, for the entire build** | No |
| Blocks other DDL / autovacuum | Yes | Yes |
| Table scans required | One | Two, plus two waits for concurrent transactions |
| Relative duration | Baseline | Roughly 2-3x longer |
| Runs inside a transaction block | Yes | **No -- not permitted** |
| On failure | Rolls back cleanly, nothing left behind | Leaves an INVALID index that must be dropped |
| Parallel workers | Yes | No |

**On a 24/7 exchange, the concurrent form is the default.** Use the plain form only on a table that is genuinely not written to during the build -- a static reference table, or a brand-new table not yet receiving traffic.

---

## Method A: `CREATE INDEX CONCURRENTLY` (default for production)

### Step A1 -- set a lock timeout for the session

```sql
SET lock_timeout = '5s';
SET maintenance_work_mem = '2GB';  -- adjust to what the instance can spare
```

`SET lock_timeout` bounds how long the build waits for its initial
`ShareUpdateExclusiveLock`. Even the concurrent form needs that lock briefly, and
without a timeout it can queue behind a long-running transaction while every
later statement on the table queues behind it.

### Step A2 -- run the build

```sql
-- NOTE: this statement MUST NOT be wrapped in BEGIN/COMMIT. PostgreSQL rejects
-- it inside a transaction block with:
--   ERROR:  CREATE INDEX CONCURRENTLY cannot run inside a transaction block
-- Many migration frameworks open a transaction implicitly around each
-- migration; that is the most common reason concurrent builds fail in a
-- deployment pipeline. Disable the framework's implicit transaction for this
-- migration, or run the statement by hand.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_trades_account_id_executed_at
    ON public.trades (account_id, executed_at DESC);
```

- **Lock level:** `ShareUpdateExclusiveLock`. Reads and writes both proceed normally throughout. It does conflict with other DDL on the same table and with autovacuum, so only one such build per table at a time.
- **Blocking risk:** low, but not zero. The build waits for all transactions that started before each of its two scan phases to finish. A single long-running transaction elsewhere in the database can stall the build indefinitely without blocking anything itself -- check for those first.
- **Transaction behavior:** cannot run inside a transaction block. It manages its own internal transactions across multiple phases.
- **Rollback:** there is no rollback. If the statement is cancelled or the session dies, PostgreSQL leaves the partially built index in place marked `INVALID`. It is invisible to the planner but still maintained by every write, so it must be dropped -- see the failed-index-build workflow.
- **Production considerations:** the build generates significant redo. Watch Aurora reader lag while it runs and be prepared to cancel if lag becomes customer-visible. Do not start one immediately before a scheduled market event or deployment.

### Step A3 -- verify validity

Run `06_post_build_validation.sql` in this directory. If the index is marked invalid, do not retry the build until the leftover has been dropped.

---

## Method B: plain `CREATE INDEX` (only for tables not being written)

```sql
BEGIN;
  SET LOCAL lock_timeout = '5s';
  CREATE INDEX idx_instrument_reference_symbol
      ON public.instrument_reference (symbol);
COMMIT;
```

- **Lock level:** `ShareLock`. Concurrent reads are fine; **every write to the table blocks for the whole build**.
- **Blocking risk:** total, for writes. On a table taking exchange traffic this is an outage for the duration.
- **Transaction behavior:** fully transactional. It can be wrapped in `BEGIN`/`COMMIT` and combined with other DDL in one atomic change.
- **Rollback:** clean. `ROLLBACK`, a cancellation, or a crash leaves no trace -- this is the one genuine advantage over the concurrent form.
- **Production considerations:** acceptable for a static reference table, a brand-new table with no traffic yet, or a non-production environment. Always set `lock_timeout` so the statement cannot form a lock queue.

---

## Method C: partitioned tables

A plain `CREATE INDEX` on a partitioned parent recurses into every partition and holds locks across all of them simultaneously. On a table with hundreds of partitions that is an unacceptable blast radius. Build it in three stages instead:

```sql
-- 1. Register the index definition on the parent without building anything.
--    ON ONLY creates an invalid parent index as a template; the parent index
--    becomes valid automatically once every partition's index is attached.
CREATE INDEX idx_trades_part_account_id
    ON ONLY public.trades (account_id);

-- 2. Build a matching index concurrently on each partition, one at a time.
CREATE INDEX CONCURRENTLY idx_trades_2026_01_account_id
    ON public.trades_2026_01 (account_id);

-- 3. Attach each partition index to the parent. This is a fast metadata
--    operation; the parent index flips to valid after the last attach.
ALTER INDEX idx_trades_part_account_id
    ATTACH PARTITION idx_trades_2026_01_account_id;
```

- **Lock level:** step 1 takes a brief `ShareUpdateExclusiveLock` on the parent only (it builds nothing). Step 2 is per-partition and non-blocking. Step 3 is a brief metadata lock.
- **Blocking risk:** minimal at every stage, which is the entire point of doing it this way.
- **Rollback:** drop the parent index; attached partition indexes are dropped with it.
- **Production considerations:** script the loop over partitions but run it serially, checking validity after each one. Repeat step 2 and 3 for every new partition created before the parent index existed.
