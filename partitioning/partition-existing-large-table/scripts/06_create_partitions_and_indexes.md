# 06_create_partitions_and_indexes

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `06_create_partitions_and_indexes.md` |
| Purpose | Creates the individual partitions and recreates indexes/constraints on the new partitioned table. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only (the query reads/writes state that only exists or is meaningful on the writer) |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | Varies by step -- read each step's own warning before executing it. |
| Required privileges | Table owner, or a role granted the `MAINTAIN` privilege on the table (PostgreSQL 16+), or a role with `pg_maintain` membership. DDL variants additionally require the privileges needed for the specific DDL statement (e.g. ownership to ALTER TABLE). |
| Prerequisites | Full read-only investigation for this workflow completed; maintenance window and second engineer approval obtained. |
| Execution order | Step 06 of workflow `partitioning/partition-existing-large-table` |
| Related scripts | 07_backfill_historical_data_batches.md |

## How to interpret / use this runbook

Each partition and each CONCURRENTLY index build is independent -- validate one partition's index build completes (not INVALID) before scripting the rest in bulk.

---

## Step 2: Create partitions

```sql
CREATE TABLE public.orders_y2024m01 PARTITION OF public.orders_partitioned
    FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');
-- Repeat for each bucket identified in script 01/02, including a few
-- future partitions ahead of the current date.
```

## Step 3: Recreate indexes

```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_orders_partitioned_account_id
    ON ONLY public.orders_partitioned (account_id);
-- On PostgreSQL, CREATE INDEX ... ON ONLY against the partitioned parent
-- registers the index definition; you must still create/attach a matching
-- index CONCURRENTLY on each existing partition individually, then
-- ALTER INDEX ... ATTACH PARTITION to link it, so no partition index build
-- ever takes a blocking lock on the whole partitioned table.
```

## Step 4: Recreate constraints

- Add the primary key on the partitioned parent (must include the partition key column(s)).
- For foreign keys FROM other tables INTO this table: PostgreSQL requires the referenced unique/PK constraint to include the partition key -- coordinate with owners of any referencing tables before finalizing the key.
- Add any CHECK constraints not already copied via `LIKE ... INCLUDING CONSTRAINTS` in script 05.

All of the above operate on the new, empty `orders_partitioned` structure and do not lock or affect the original production table.
