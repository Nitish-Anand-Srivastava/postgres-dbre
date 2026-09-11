# 02_explain_guidance

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `02_explain_guidance.md` |
| Purpose | Guidance for using EXPLAIN to confirm whether a specific query against a partitioned table is pruning effectively. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only (the query reads/writes state that only exists or is meaningful on the writer) |
| Safety | DOCUMENTATION -- no SQL executed by this file itself |
| Expected impact | None from this file; running EXPLAIN itself never executes the query. |
| Required privileges | Table owner, or a role granted the `MAINTAIN` privilege on the table (PostgreSQL 16+), or a role with `pg_maintain` membership. DDL variants additionally require the privileges needed for the specific DDL statement (e.g. ownership to ALTER TABLE). |
| Prerequisites | Full read-only investigation for this workflow completed; maintenance window and second engineer approval obtained. |
| Execution order | Step 02 of workflow `partitioning/partition-pruning` |
| Related scripts | ../../query-optimization/analyze-query-plan/README.md |

## How to interpret / use this runbook

Confirm the rewritten query's plan shows the expected Subplans Removed count before considering the investigation complete.

---

Run `EXPLAIN <query>;` (no ANALYZE needed -- pruning is a planning-time decision) against the query in question. In the plan:

- Look for an `Append` or `MergeAppend` node listing only the specific partition subplans expected to contain matching data -- this confirms pruning worked.
- A count of `Subplans Removed: N` confirms the planner successfully excluded N partitions.
- If EVERY partition appears as a subplan despite a WHERE clause that should only match one, the filter expression is likely not directly comparable to the partition key (e.g. `WHERE created_at::date = ...` wrapping the column in a cast the planner cannot reason about generically -- rewrite as a plain range comparison: `WHERE created_at >= '...' AND created_at < '...'`).
