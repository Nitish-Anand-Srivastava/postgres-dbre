# 02_detach_and_archive

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `02_detach_and_archive.md` |
| Purpose | Detaches the identified old partition and archives it before dropping. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only (the query reads/writes state that only exists or is meaningful on the writer) |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | Varies by step -- read each step's own warning before executing it. |
| Required privileges | Table owner, or a role granted the `MAINTAIN` privilege on the table (PostgreSQL 16+), or a role with `pg_maintain` membership. DDL variants additionally require the privileges needed for the specific DDL statement (e.g. ownership to ALTER TABLE). |
| Prerequisites | Full read-only investigation for this workflow completed; maintenance window and second engineer approval obtained. |
| Execution order | Step 02 of workflow `archival-and-data-lifecycle/archive-partition` |
| Related scripts | ../archive-large-table/scripts/02_export_to_cold_storage.md |

## How to interpret / use this runbook

Do not DROP the detached table until its export has been independently validated, exactly as in archive-large-table.

---

```sql
-- CONCURRENTLY avoids a blocking AccessExclusiveLock on the parent table for
-- the duration (PostgreSQL 14+). It cannot run inside an explicit transaction
-- block.
ALTER TABLE public.orders DETACH PARTITION public.orders_y2022m11 CONCURRENTLY;
```

The detached table (`orders_y2022m11`) is now a standalone ordinary table, no longer part of the partitioned parent and no longer receiving any pruning-based query traffic. Export it to cold storage using the same approach as archive-large-table script 02, validate with the same row-count/checksum approach as scripts 03-04, and only then:

```sql
DROP TABLE public.orders_y2022m11; -- irreversible; only after validated export
```
