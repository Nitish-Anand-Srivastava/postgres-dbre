# 08_dual_write_or_cdc_sync_delta

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `08_dual_write_or_cdc_sync_delta.md` |
| Purpose | Keeps the new partitioned table current with ongoing writes made to the original table while the batched backfill (script 07) is in progress. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only (the query reads/writes state that only exists or is meaningful on the writer) |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | Varies by step -- read each step's own warning before executing it. |
| Required privileges | Table owner, or a role granted the `MAINTAIN` privilege on the table (PostgreSQL 16+), or a role with `pg_maintain` membership. DDL variants additionally require the privileges needed for the specific DDL statement (e.g. ownership to ALTER TABLE). |
| Prerequisites | Full read-only investigation for this workflow completed; maintenance window and second engineer approval obtained. |
| Execution order | Step 08 of workflow `partitioning/partition-existing-large-table` |
| Related scripts | 09_validation_row_counts_checksums.sql |

## How to interpret / use this runbook

Choose Option A for simplicity on moderate-throughput tables; choose Option B for the very highest-throughput ledger/order tables where trigger overhead on every write is unacceptable.

---

## Option A: Trigger-based dual write (simplest, most portable)

```sql
CREATE OR REPLACE FUNCTION public.sync_orders_to_partitioned() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO public.orders_partitioned VALUES (NEW.*) ON CONFLICT DO NOTHING;
    ELSIF TG_OP = 'UPDATE' THEN
        UPDATE public.orders_partitioned SET (col1, col2, ...) = (NEW.col1, NEW.col2, ...)
            WHERE id = NEW.id;
    ELSIF TG_OP = 'DELETE' THEN
        DELETE FROM public.orders_partitioned WHERE id = OLD.id;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_sync_orders_partitioned
    AFTER INSERT OR UPDATE OR DELETE ON public.orders
    FOR EACH ROW EXECUTE FUNCTION public.sync_orders_to_partitioned();
```
`CREATE TRIGGER` takes a brief `ShareRowExclusiveLock` -- schedule this specific statement for a lower-traffic moment even though the rest of this runbook is online, and confirm it completes quickly (it should, since it only adds metadata, not data).

## Option B: Logical replication (larger tables, lower per-write overhead)

Create a publication on the source table and subscribe from the new table's database/schema via `CREATE PUBLICATION` / `CREATE SUBSCRIPTION`, or use AWS DMS for a managed CDC pipeline. This avoids adding a synchronous trigger to the hot write path at the cost of additional operational complexity (monitoring replication slot lag per replication-and-ha/replication-health) and is generally preferable for the very highest-throughput tables.

Whichever option is chosen, it must remain active from before the backfill starts until after the cutover (script 10) completes.
