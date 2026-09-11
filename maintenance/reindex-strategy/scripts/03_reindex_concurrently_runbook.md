# 03_reindex_concurrently_runbook

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `03_reindex_concurrently_runbook.md` |
| Purpose | Guarded runbook for executing a batched REINDEX CONCURRENTLY campaign across the candidates identified in script 01. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only (the query reads/writes state that only exists or is meaningful on the writer) |
| Safety | LOW RISK WRITE (REINDEX CONCURRENTLY takes SHARE UPDATE EXCLUSIVE, not ACCESS EXCLUSIVE; ordinary reads/writes continue -- see runbook for lock/disk-space details) |
| Expected impact | Real I/O/CPU load for the duration of each index rebuild, plus roughly double that index's disk space temporarily; blocks other DDL and VACUUM on the same table until each REINDEX CONCURRENTLY completes. |
| Required privileges | Table owner, or a role granted the `MAINTAIN` privilege on the table (PostgreSQL 16+), or a role with `pg_maintain` membership. DDL variants additionally require the privileges needed for the specific DDL statement (e.g. ownership to ALTER TABLE). |
| Prerequisites | Full read-only investigation for this workflow completed; maintenance window and second engineer approval obtained. |
| Execution order | Step 03 of workflow `maintenance/reindex-strategy` |
| Related scripts | 01_reindex_candidate_ranking.sql, 02_reindex_progress_monitor.sql, ../../tables-and-indexes/invalid-indexes/README.md |

## How to interpret / use this runbook

Work through one index at a time within a batch, confirming completion via the progress monitor before moving to the next -- do not launch an entire batch's REINDEX statements concurrently against the same table.

---

## Plan the batches first

Using `01_reindex_candidate_ranking.sql`'s output, group candidates into batches sized so that the cumulative disk space needed (roughly the sum of each batch's candidate index sizes, since the old and new index coexist briefly) stays comfortably within available headroom -- do not plan a batch that could exhaust disk space mid-rebuild.

## Run one index at a time within a batch

```sql
REINDEX INDEX CONCURRENTLY public.idx_orders_customer_id;
```

Replace the index name with the actual next candidate from script 01's ranked output for this batch. `REINDEX INDEX CONCURRENTLY` (unlike plain `REINDEX INDEX`) does not take an ACCESS EXCLUSIVE lock, so ordinary reads/writes against the table continue throughout -- but it does take a SHARE UPDATE EXCLUSIVE lock, which blocks other DDL and a concurrent VACUUM on the same table, so do not start the next index on the same table until this one completes.

## Monitor before starting the next

Re-run `02_reindex_progress_monitor.sql` and confirm no row remains for this index before starting the next one in the batch.

## If a REINDEX CONCURRENTLY fails partway

PostgreSQL 14+ automatically cleans up an INVALID index left behind by a failed `REINDEX CONCURRENTLY` on its next attempt; on any version, check for an INVALID index afterward (`tables-and-indexes/invalid-indexes`) and drop it with `DROP INDEX CONCURRENTLY` before retrying, since a leftover invalid index otherwise just consumes space without serving any query.

## Between batches

Confirm disk headroom is back to a comfortable level (the temporary extra space from the completed batch's old indexes has been released) before starting the next batch, and prefer scheduling batches during the cluster's lowest-traffic window even though `CONCURRENTLY` does not block ordinary queries -- the rebuild still consumes real I/O and CPU shared with production traffic.
