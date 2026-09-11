# 02_batched_purge

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `02_batched_purge.md` |
| Purpose | Batched purge template for confirmed-ephemeral data with no retention requirement. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only (the query reads/writes state that only exists or is meaningful on the writer) |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | Varies by step -- read each step's own warning before executing it. |
| Required privileges | Table owner, or a role granted the `MAINTAIN` privilege on the table (PostgreSQL 16+), or a role with `pg_maintain` membership. DDL variants additionally require the privileges needed for the specific DDL statement (e.g. ownership to ALTER TABLE). |
| Prerequisites | Full read-only investigation for this workflow completed; maintenance window and second engineer approval obtained. |
| Execution order | Step 02 of workflow `archival-and-data-lifecycle/purge-old-data` |
| Related scripts | ../../maintenance/README.md |

## How to interpret / use this runbook

Confirm zero compliance retention requirement before running -- this data is discarded, not archived, and is not recoverable after each batch commits (barring point-in-time recovery).

---

```sql
-- Same batching discipline as archive-large-table's deletion step, but
-- without any preceding export -- this data is being discarded, not archived.
\set batch_size 5000
\set expiry_column 'expires_at'
DELETE FROM public.sessions
WHERE ctid IN (
    SELECT ctid FROM public.sessions
    WHERE expires_at < now()
    LIMIT 5000
);
-- Repeat/COMMIT per batch (drive from an external loop or a PL/pgSQL
-- procedure called via CALL) until GET DIAGNOSTICS reports 0 rows deleted.
```
