# 02_export_to_cold_storage

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `02_export_to_cold_storage.md` |
| Purpose | Exports the to-be-archived rows to durable cold storage before any deletion, using batched, checkpointed exports. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only (the query reads/writes state that only exists or is meaningful on the writer) |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | Varies by step -- read each step's own warning before executing it. |
| Required privileges | Table owner, or a role granted the `MAINTAIN` privilege on the table (PostgreSQL 16+), or a role with `pg_maintain` membership. DDL variants additionally require the privileges needed for the specific DDL statement (e.g. ownership to ALTER TABLE). |
| Prerequisites | Full read-only investigation for this workflow completed; maintenance window and second engineer approval obtained. |
| Execution order | Step 02 of workflow `archival-and-data-lifecycle/archive-large-table` |
| Related scripts | 03_validate_export_row_counts.sql |

## How to interpret / use this runbook

This step only reads from the source table -- it does not modify or lock it beyond a normal read. Safe to run against production at any time; batch it to avoid a single very long-running read transaction on a huge historical range.

---

## Option A: Export to S3 via aws_s3 extension (Aurora-supported)

```sql
-- aws_s3 is an AWS-provided extension available on Aurora PostgreSQL for
-- direct export to S3 without an intermediate application hop.
CREATE EXTENSION IF NOT EXISTS aws_s3 CASCADE;

SELECT aws_s3.query_export_to_s3(
    'SELECT * FROM public.orders WHERE created_at < ''2023-01-01''::timestamptz',
    aws_commons.create_s3_uri('your-archive-bucket', 'orders/pre-2023.csv', 'us-east-1')
);
```
This runs as a read-only query against the source table (no lock beyond a normal read snapshot) and streams results directly to S3.

## Option B: Export to a separate archive database/table

```sql
-- If the archive destination is another PostgreSQL/Aurora database, use
-- postgres_fdw or dblink to copy in batches:
INSERT INTO archive_db.orders_archive
SELECT * FROM public.orders
WHERE created_at < '2023-01-01'::timestamptz
  AND id > :last_exported_id
ORDER BY id
LIMIT 10000;
-- Repeat, advancing :last_exported_id, until fully exported. Batching avoids
-- one enormous read/write transaction and its associated WAL/replica-lag
-- impact on both the source and destination.
```

Whichever option is used, confirm the exported data is genuinely queryable at the destination (not just 'the export command succeeded') before proceeding.
