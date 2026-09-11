# 08_execution_plan_guidance

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `08_execution_plan_guidance.md` |
| Purpose | Guidance for safely obtaining and reading an execution plan for the slow query. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only (the query reads/writes state that only exists or is meaningful on the writer) |
| Safety | DOCUMENTATION -- no SQL is executed by this file itself |
| Expected impact | None from this file; impact depends entirely on which guidance the operator chooses to execute. |
| Required privileges | Same as the query being analyzed. |
| Prerequisites | Query text/queryid identified from scripts 02 or 03. |
| Execution order | Step 08 of workflow `performance/slow-queries` |
| Related scripts | ../../query-optimization/analyze-query-plan/README.md |

## How to interpret / use this runbook

Use this guidance to safely capture a plan for the slow query identified in scripts 02/03, then follow query-optimization/analyze-query-plan for a deeper structured plan-reading workflow.

---

## EXPLAIN vs. EXPLAIN ANALYZE

* `EXPLAIN (FORMAT TEXT) <query>;` shows the planner's *estimated* plan and cost without executing the query. Always safe to run in production, including against write statements, because it never executes anything.
* `EXPLAIN ANALYZE <query>;` **actually executes the query** (including any writes it contains) and measures real timing per plan node. Never run `EXPLAIN ANALYZE` against an UPDATE/DELETE/INSERT statement in production unless it is wrapped in a transaction you intend to `ROLLBACK`, and never run it against a query you are not prepared to have actually complete (it will take at least as long as the original slow query, possibly longer due to instrumentation overhead).
* For a read query you want to time-box, prefer:
  ```sql
  SET LOCAL statement_timeout = '5s';
  EXPLAIN (ANALYZE, BUFFERS, TIMING, FORMAT TEXT) <query>;
  ```
  so a misbehaving plan cannot itself become a new incident.
* PostgreSQL 17 adds `EXPLAIN (ANALYZE, SERIALIZE)` to additionally measure the time spent converting result rows to wire format -- useful when a query returns a very large result set and you suspect client-side serialization, not the plan itself, dominates latency.
* For an UPDATE/DELETE/INSERT you must analyze safely, run inside an explicit transaction and roll back:
  ```sql
  BEGIN;
  EXPLAIN (ANALYZE, BUFFERS) UPDATE ...;
  ROLLBACK;
  ```
  Be aware this still takes locks for the duration of the statement and generates the same row-level work as a real execution -- do not do this against a hot production table without a maintenance window or a replica.

## Reading the plan

* Compare `rows=` (estimated) against `actual rows=` (from EXPLAIN ANALYZE) at each node -- large gaps indicate stale/insufficient statistics.
* Look for `Seq Scan` on large tables where an `Index Scan`/`Index Only Scan` would be expected.
* Look for `Sort Method: external merge Disk` or `Batches: N (originally M)` in hash operations -- both indicate spilling to disk due to insufficient `work_mem` for that operation.
* `Nested Loop` joining two large row sets without a supporting index on the inner side is the classic pattern behind the query-optimization/nested-loop-problems workflow.
