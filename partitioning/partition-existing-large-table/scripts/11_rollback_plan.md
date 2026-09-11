# 11_rollback_plan

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `11_rollback_plan.md` |
| Purpose | Rollback procedure if validation fails post-cutover, or if the cutover itself must be aborted. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only (the query reads/writes state that only exists or is meaningful on the writer) |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | Varies by step -- read each step's own warning before executing it. |
| Required privileges | Table owner, or a role granted the `MAINTAIN` privilege on the table (PostgreSQL 16+), or a role with `pg_maintain` membership. DDL variants additionally require the privileges needed for the specific DDL statement (e.g. ownership to ALTER TABLE). |
| Prerequisites | Full read-only investigation for this workflow completed; maintenance window and second engineer approval obtained. |
| Execution order | Step 11 of workflow `partitioning/partition-existing-large-table` |
| Related scripts | ../partition-maintenance/README.md |

## How to interpret / use this runbook

Keep this runbook open and reviewed by a second engineer during the cutover window (script 10) -- do not read it for the first time after something has already gone wrong.

---

## If validation fails BEFORE cutover (script 09 shows a mismatch)

- Do not proceed to script 10. Investigate and fix the dual-write/CDC mechanism gap (script 08), then re-run validation.

## If an issue is discovered AFTER cutover (script 10 already committed)

```sql
BEGIN;
  ALTER TABLE public.orders RENAME TO orders_partitioned_rollback;
  ALTER TABLE public.orders_pre_partition_backup RENAME TO orders;
COMMIT;
```
This reverses the rename swap, restoring the original (pre-partition) table as `public.orders` immediately. Any writes that occurred against the partitioned table between cutover and rollback will need to be reconciled manually -- for this reason, keep the post-cutover validation-and-smoke-test window (immediately after script 10) as short as practically possible, and treat a rollback beyond that immediate window as a data-reconciliation exercise, not a simple rename.

## Final cleanup (only after a confirmed, stable rollback-safe period)

```sql
DROP TABLE public.orders_pre_partition_backup; -- only after full confidence
```
Do not drop the renamed backup table until you have observed the new partitioned table under full production load for a duration your organization's change-management policy considers safe (commonly one full business cycle).
