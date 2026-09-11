# 04_type_change_rewrite_reference

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `04_type_change_rewrite_reference.md` |
| Purpose | Reference classification of column type changes into metadata-only and full-rewrite, with the direct-execution runbook for the metadata-only cases. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only (the query reads/writes state that only exists or is meaningful on the writer) |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | Varies by step -- read each step's own warning before executing it. |
| Required privileges | Table owner, or a role granted the `MAINTAIN` privilege on the table (PostgreSQL 16+), or a role with `pg_maintain` membership. DDL variants additionally require the privileges needed for the specific DDL statement (e.g. ownership to ALTER TABLE). |
| Prerequisites | Scripts 01-03 completed so the exact column definition, dependencies, and table size are known. |
| Execution order | Step 04 of workflow `schema-changes/column-type-change` |
| Related scripts | 05_online_column_type_change_runbook.md |

## How to interpret / use this runbook

Classify the change here before doing anything else, and be exact about the type modifiers -- 'widening the amount column' is not a classification, numeric(18,8) to numeric(20,8) is. If the row says No, use the runbook in this file and the change takes milliseconds. If it says Yes and the table is anything but small, go to script 05; do not look for a way to make the rewrite faster, because there is not one. The sequence headroom query at the end is the one thing here that should be run routinely rather than during a change: reaching an integer ceiling on a live trades table is an outage with no fast fix, and the only real defense is finding it a year early.

---

## Which changes avoid a rewrite

PostgreSQL skips the table rewrite only when the new type is binary-coercible
from the old one and nothing needs rechecking. That is a short list.

| Change | Rewrite? | Notes |
|---|---|---|
| `varchar(n)` to `varchar(m)` where m > n | **No** | Widening a length limit is metadata-only |
| `varchar(n)` to `text` | **No** | Removing the limit is metadata-only |
| `text` to `varchar(n)` | Yes | Every row must be length-checked |
| `varchar(n)` to `varchar(m)` where m < n | Yes | Narrowing requires checking every value |
| `numeric(p,s)` to `numeric(p2,s)` where p2 > p, same scale | **No** | Widening precision at the same scale is metadata-only |
| `numeric(p,s)` to any different scale | Yes | Values must be rescaled |
| `numeric` to `numeric` unconstrained | **No** | Removing the constraint is metadata-only |
| `integer` to `bigint` | Yes | Different physical width -- always rewrites |
| `bigint` to `integer` | Yes | Narrowing, and can fail on out-of-range values |
| `timestamp` to `timestamptz` | **Only if** session `TimeZone` is UTC | Otherwise every value must be shifted |
| Anything with a `USING` expression | Yes | The expression must be evaluated per row |

**The most common exchange case, `integer` to `bigint` on a trades or ledger key,
always rewrites.** There is no shortcut. That is precisely why it must be started
months before the ceiling is reached, using the online pattern in script 05.

---

## Runbook for a metadata-only change

Only for a change confirmed **No** in the rewrite column above.

```sql
BEGIN;
  SET LOCAL lock_timeout = '3s';

  ALTER TABLE public.orders
      ALTER COLUMN client_order_reference TYPE varchar(128);
  -- Widening from varchar(64): metadata only, no scan, no rewrite.
COMMIT;
```

- **Lock level:** `AccessExclusiveLock`, held for milliseconds.
- **Blocking risk:** near zero with the timeout set. Without a timeout, a statement that cannot get its lock queues and stalls every later query on the table.
- **Transaction behavior:** fully transactional; can be combined with other DDL in the same transaction.
- **Rollback:** clean. `ROLLBACK` undoes it entirely, and a crash or failover does the same.
- **Production considerations:** safe during trading hours. Dependent views still need dropping and recreating if they expose the column, so check `02_dependent_objects_inventory.sql` output even for a metadata-only change.

If it fails with `canceling statement due to lock timeout`, that is correct
behavior. Check `large-table-ddl` script 04 for long-running transactions and
retry in a loop rather than raising the timeout.

---

## Checking headroom before an integer ceiling is reached

Read-only, safe to run at any time. Run it on a schedule, not once:

```sql
-- How close is each sequence to its maximum? Run this monthly on any table
-- taking exchange-scale insert volume. int4 tops out at 2,147,483,647; a table
-- inserting ten million rows a day reaches that in under a year.
SELECT schemaname, sequencename, last_value, max_value,
       round(100.0 * last_value / NULLIF(max_value, 0), 2) AS pct_consumed
FROM pg_sequences
ORDER BY pct_consumed DESC NULLS LAST;
```

Anything above 50 percent consumed on a high-volume table should already have a
widening project scheduled. Above 80 percent it is urgent, because the online
pattern itself takes weeks on a large table.
