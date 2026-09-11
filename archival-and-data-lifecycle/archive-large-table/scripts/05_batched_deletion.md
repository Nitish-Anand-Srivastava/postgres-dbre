# 05_batched_deletion

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `05_batched_deletion.md` |
| Purpose | Deletes the validated, archived rows from the source table in small, monitored batches -- the highest-risk step in this workflow. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only (the query reads/writes state that only exists or is meaningful on the writer) |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | Varies by step -- read each step's own warning before executing it. |
| Required privileges | Table owner, or a role granted the `MAINTAIN` privilege on the table (PostgreSQL 16+), or a role with `pg_maintain` membership. DDL variants additionally require the privileges needed for the specific DDL statement (e.g. ownership to ALTER TABLE). |
| Prerequisites | Full read-only investigation for this workflow completed; maintenance window and second engineer approval obtained. |
| Execution order | Step 05 of workflow `archival-and-data-lifecycle/archive-large-table` |
| Related scripts | 06_post_archive_vacuum.sql |

## How to interpret / use this runbook

This is the irreversible step in the workflow (barring a full restore from backup). Do not begin until every validation step above has passed without exception.

---

## Prerequisites for this step

- Scripts 01-04 completed with full validation success.
- A recent, verified backup/snapshot exists independent of this archive (Aurora automated backups/snapshots satisfy this, but confirm the retention window covers your rollback needs).

## Batched delete template

```sql
-- Never run a single unbounded DELETE against a large historical range: it
-- holds row locks for the whole statement, generates a single enormous WAL
-- burst, and can bloat the table (freed space is not reclaimed by DELETE
-- itself -- a subsequent VACUUM in script 06 is required for that).
\set batch_size 5000
DO $$
DECLARE
    deleted_count integer;
BEGIN
    LOOP
        DELETE FROM public.orders
        WHERE id IN (
            SELECT id FROM public.orders
            WHERE created_at < '2023-01-01'::timestamptz
            ORDER BY id
            LIMIT 5000
        );
        GET DIAGNOSTICS deleted_count = ROW_COUNT;
        EXIT WHEN deleted_count = 0;
        COMMIT;
        PERFORM pg_sleep(0.25); -- brief pause between batches to smooth I/O/WAL
    END LOOP;
END $$;
```
Note: a plain `DO` block cannot COMMIT inside itself in vanilla PL/pgSQL prior to procedures; use a PL/pgSQL **procedure** called via `CALL`, or drive the loop from an external script/psql `\watch`-based loop, so each batch genuinely commits independently. Monitor storage-and-capacity/wal-generation and replication-and-ha/reader-lag-investigation while this runs, and slow down (increase pg_sleep, or reduce batch_size) if either climbs beyond tolerance.
