# 07_backfill_historical_data_batches

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `07_backfill_historical_data_batches.md` |
| Purpose | Backfills historical data from the original table into the new partitioned table in small, committed batches. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only (the query reads/writes state that only exists or is meaningful on the writer) |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | Varies by step -- read each step's own warning before executing it. |
| Required privileges | Table owner, or a role granted the `MAINTAIN` privilege on the table (PostgreSQL 16+), or a role with `pg_maintain` membership. DDL variants additionally require the privileges needed for the specific DDL statement (e.g. ownership to ALTER TABLE). |
| Prerequisites | Full read-only investigation for this workflow completed; maintenance window and second engineer approval obtained. |
| Execution order | Step 07 of workflow `partitioning/partition-existing-large-table` |
| Related scripts | 08_dual_write_or_cdc_sync_delta.md |

## How to interpret / use this runbook

This step can safely take hours to days for a very large table -- there is no rush, and slower is safer. It runs fully online against a live production table.

---

## Batched backfill template

Never copy the whole table in one transaction -- it will hold a long-running transaction (delaying vacuum cleanup and risking XID-age impact per transactions-and-xid/xid-wraparound-risk) and generate a single enormous burst of WAL that can spike replica lag.

```sql
-- Repeat this loop (via a script/psql \watch, or an application-side batch job)
-- advancing :batch_start_id / :batch_end_id each iteration until the source
-- table is fully copied. Keep batches small enough to complete in well under a
-- second each on your hardware -- a few thousand to a low tens-of-thousands of
-- rows is a typical starting point; tune based on observed replica lag and
-- lock-wait impact during a test run.
\set batch_start_id 0
\set batch_size 5000
INSERT INTO public.orders_partitioned
SELECT * FROM public.orders
WHERE id > :batch_start_id
ORDER BY id
LIMIT :batch_size
ON CONFLICT DO NOTHING;
-- COMMIT after each batch (autocommit in psql commits each statement by
-- default; if wrapped in an explicit transaction elsewhere, COMMIT here).
```

Monitor WAL generation (storage-and-capacity/wal-generation) and Aurora replica lag (replication-and-ha/reader-lag-investigation) while backfilling and slow down/pause the batch loop if either climbs beyond your accepted tolerance.
