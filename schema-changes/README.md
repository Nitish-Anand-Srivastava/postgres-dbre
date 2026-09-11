# Schema Changes and DDL

**Category:** `schema-changes`

This is the index for the `schema-changes/` category: every workflow
(issue directory) below addresses a distinct, real operational problem or
DBA use case for this Aurora PostgreSQL toolkit, per the repository's
one-parent-directory-per-problem design. Each workflow directory is
self-contained -- its own `README.md` (problem description, symptoms,
business impact, root causes, investigation strategy, prerequisites,
interpretation guide, remediation options, production safety, and
escalation criteria) and a `scripts/` directory of numbered, read-only-by
-default investigation scripts (see each workflow's `scripts/README.md`
for the full script-by-script execution table).

## Workflows

| Workflow | Summary |
| --- | --- |
| [`safe-index-creation`](safe-index-creation/README.md) | A new index is needed on a production table and the question is how to build it without blocking the trading path. This is the entry point for the whole index-creation family: it establishes whether the index is genuinely needed (a surprising proportion of proposed indexes are already covered by an existing one), which build method is appropriate for the table's size and write rate, and what the lock and rollback consequences of each option are. The single most important decision it drives is plain `CREATE INDEX` versus `CREATE INDEX CONCURRENTLY` -- the first takes a lock that blocks every write to the table for the entire build, and the second does not, at the cost of being slower, non-transactional, and able to fail in a way that leaves an unusable index behind. |
| [`concurrent-index-build`](concurrent-index-build/README.md) | `CREATE INDEX CONCURRENTLY` is the only index build method acceptable on a live exchange table, and it has a specific set of failure modes that have nothing to do with the index itself. It takes two full passes over the table and, between and after those passes, waits for every transaction that started before each pass to finish. That means a single long-running or idle-in-transaction session anywhere in the database -- one that never touches the target table at all -- can stall the build indefinitely. It also cannot run inside a transaction block, which is the reason most deployment pipelines fail to run it. This workflow covers the pre-flight checks that prevent a stall, live monitoring of a build in progress, and validation afterwards. |
| [`failed-index-build`](failed-index-build/README.md) | An index build did not complete and left an INVALID index behind. This is the specific, expected aftermath of a cancelled or interrupted `CREATE INDEX CONCURRENTLY` (and of `REINDEX CONCURRENTLY`), and it is worse than it looks: the leftover index is completely invisible to the planner, so it provides zero query benefit, while still being fully maintained by every insert and update on the table and fully processed by every vacuum. It is strictly worse than having no index at all. This workflow finds these leftovers, establishes why the build failed so the retry does not repeat it, cleans them up safely, and confirms the table is back to a known-good state. |
| [`large-table-ddl`](large-table-ddl/README.md) | A schema change is needed on a table large enough and hot enough that the usual answer -- just run the ALTER -- is unacceptable. The governing insight is that on a live exchange the lock is the risk, not the work: PostgreSQL takes an `AccessExclusiveLock` for most `ALTER TABLE` variants, and while that lock is held every query against the table -- including plain SELECTs on the order-matching path -- queues behind it. Worse, a *pending* exclusive lock request blocks every later request too, so a statement that merely waits for its lock takes the application down just as effectively as one that holds it. This workflow classifies the intended change by lock level and rewrite behavior, checks the table is in a state where DDL can safely be attempted, and executes it with the lock-timeout-and-retry discipline that makes the difference between a routine change and an outage. |
| [`column-type-change`](column-type-change/README.md) | A column's data type must change -- the classic case on an exchange being an `integer` surrogate key on the trades or ledger table approaching the two-billion ceiling and needing to become `bigint`, or a `numeric` price column needing more scale. `ALTER TABLE ... ALTER COLUMN ... TYPE` is deceptively short for what it does: for most type changes it rewrites every row of the table and rebuilds every index, holding an `AccessExclusiveLock` throughout, which on a large exchange table is an outage measured in hours. A small number of type changes are metadata-only and genuinely instant. This workflow establishes which category your change falls into, inventories everything that depends on the column, and provides the online add-column-and-swap pattern for the cases where a rewrite is not acceptable. |
| [`add-column-large-table`](add-column-large-table/README.md) | Adding a column to a large production table is the schema change most often assumed to be trivial, and most of the time it now is -- but the exceptions are severe and they are not obvious from the statement text. Since PostgreSQL 11, `ADD COLUMN` with a constant default is a catalog-only operation: the default is stored once in `pg_attribute` and materialized lazily as rows are updated, so the statement takes an `AccessExclusiveLock` for milliseconds regardless of table size. But a *volatile* default such as `now()` or `gen_random_uuid()`, a `GENERATED ALWAYS AS ... STORED` column, or adding `NOT NULL` in the same statement without a default, each force a full table rewrite that holds that lock for hours on an exchange-scale table. This workflow tells the two cases apart before the statement is run, not after. |
| [`add-index-large-table`](add-index-large-table/README.md) | An index is needed on a table large enough that the build itself is a production event: hours of elapsed time, substantial redo, sustained Aurora reader lag, and a permanent increase in write amplification on every subsequent insert and update. This workflow is deliberately more sceptical than safe-index-creation. Before committing to the build it asks whether the index is justified at all -- is there real evidence of the sequential scans it would eliminate, is the access pattern already covered by an existing index's leading columns, and is the table's write rate high enough that the ongoing maintenance cost outweighs the query benefit. Only then does it cover the build, which on a table this size must always be concurrent and should usually be partial. |
| [`drop-index-safely`](drop-index-safely/README.md) | An index looks unused and someone wants to remove it. Dropping an index is trivially easy and disproportionately dangerous: the statement takes a second, and if the index turns out to have been serving a query that only runs at month-end reconciliation, the consequence is a full sequential scan of a multi-hundred-gigabyte table discovered under time pressure during the regulatory reporting window. This workflow is therefore built around evidence and reversibility rather than around the statement itself. It establishes that the index is genuinely unused across every instance and a full business cycle, confirms it is not structurally required, rehearses the drop inside a transaction that is then rolled back, and only then removes it -- concurrently, so the removal itself blocks nothing. |
| [`ddl-lock-investigation`](ddl-lock-investigation/README.md) | A schema change is stuck, or a schema change has stalled the application, and you need to know exactly what is holding what. The mechanism behind almost every incident of this shape is the same and is worth understanding before reading any output: when a DDL statement requests `AccessExclusiveLock` and cannot get it immediately, PostgreSQL queues that request -- and then queues every *subsequent* lock request on the same table behind it, including plain `SELECT`s that would not have conflicted with the current holders at all. So a single long-running read, plus one waiting `ALTER TABLE`, is enough to freeze every query against the orders table while nothing is actually doing any work. This workflow finds the head of that queue, identifies the root blocker, and provides the guarded remediation. |

## Related Categories

- [`concurrency-and-locking/blocked-queries`](../../concurrency-and-locking/blocked-queries/README.md)
- [`concurrency-and-locking/ddl-blocking`](../../concurrency-and-locking/ddl-blocking/README.md)
- [`concurrency-and-locking/idle-in-transaction`](../../concurrency-and-locking/idle-in-transaction/README.md)
- [`concurrency-and-locking/lock-contention`](../../concurrency-and-locking/lock-contention/README.md)
- [`concurrency-and-locking/long-running-transactions`](../../concurrency-and-locking/long-running-transactions/README.md)
- [`partitioning/partition-existing-large-table`](../../partitioning/partition-existing-large-table/README.md)
- [`query-optimization/inefficient-index-usage`](../../query-optimization/inefficient-index-usage/README.md)
- [`query-optimization/query-plan-regression`](../../query-optimization/query-plan-regression/README.md)
- [`storage-and-capacity/index-growth`](../../storage-and-capacity/index-growth/README.md)
- [`storage-and-capacity/table-growth`](../../storage-and-capacity/table-growth/README.md)
- [`tables-and-indexes/duplicate-indexes`](../../tables-and-indexes/duplicate-indexes/README.md)
- [`tables-and-indexes/invalid-indexes`](../../tables-and-indexes/invalid-indexes/README.md)
- [`tables-and-indexes/missing-index-candidates`](../../tables-and-indexes/missing-index-candidates/README.md)
- [`tables-and-indexes/sequential-scan-investigation`](../../tables-and-indexes/sequential-scan-investigation/README.md)
- [`tables-and-indexes/unused-indexes`](../../tables-and-indexes/unused-indexes/README.md)
- [`transactions-and-xid/prepared-transactions`](../../transactions-and-xid/prepared-transactions/README.md)
- [`vacuum-and-autovacuum/index-bloat`](../../vacuum-and-autovacuum/index-bloat/README.md)

Start with the workflow whose title most closely matches the symptom you are
investigating; if uncertain, `database-health/comprehensive-health-check`
and `incident-response/production-triage` both provide a broad first pass
that surfaces which specific workflow to open next.
