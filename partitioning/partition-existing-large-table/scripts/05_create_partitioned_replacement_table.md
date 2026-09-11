# 05_create_partitioned_replacement_table

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `05_create_partitioned_replacement_table.md` |
| Purpose | Creates the new partitioned replacement table structure (empty), matching the source table's columns and defaults. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only (the query reads/writes state that only exists or is meaningful on the writer) |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | Varies by step -- read each step's own warning before executing it. |
| Required privileges | Table owner, or a role granted the `MAINTAIN` privilege on the table (PostgreSQL 16+), or a role with `pg_maintain` membership. DDL variants additionally require the privileges needed for the specific DDL statement (e.g. ownership to ALTER TABLE). |
| Prerequisites | Full read-only investigation for this workflow completed; maintenance window and second engineer approval obtained. |
| Execution order | Step 05 of workflow `partitioning/partition-existing-large-table` |
| Related scripts | 06_create_partitions_and_indexes.md |

## How to interpret / use this runbook

This step is fully additive and does not touch the existing production table -- safe to run at any time.

---

## Step 1: Create the new partitioned parent table

Choose ONE partitioning strategy based on the distribution analysis in script 01:

**Range partitioning (time-series, e.g. order/ledger history by month):**
```sql
CREATE TABLE public.orders_partitioned (
    LIKE public.orders INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING IDENTITY
) PARTITION BY RANGE (created_at);
```

**List partitioning (discrete categories, e.g. by tenant/exchange region):**
```sql
CREATE TABLE public.orders_partitioned (
    LIKE public.orders INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING IDENTITY
) PARTITION BY LIST (region_code);
```

**Hash partitioning (even distribution with no natural range/list key, e.g. by account_id for pure write-scaling rather than pruning):**
```sql
CREATE TABLE public.orders_partitioned (
    LIKE public.orders INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING IDENTITY
) PARTITION BY HASH (account_id);
```

Notes:
- `LIKE ... INCLUDING CONSTRAINTS` copies CHECK constraints but NOT foreign keys or the primary key as a partitioned-table-compatible constraint automatically -- add the primary key explicitly and ensure it includes the partition key column(s) (a hard PostgreSQL requirement for partitioned tables).
- This CREATE TABLE is a metadata-only operation on an empty table and is fast and low-risk; it does not touch the original table at all.
