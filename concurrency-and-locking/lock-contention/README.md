# Lock Contention

**Category:** Locking and Concurrency | **Workflow:** `concurrency-and-locking/lock-contention`

## 1. Problem Description

Broader, sustained lock contention across the workload (not just one isolated blocked session) -- many sessions repeatedly waiting on locks, degrading overall throughput and latency.

## 2. Typical Symptoms

- Elevated Lock wait_event_type share in overall session load.
- Throughput degradation correlated with lock waits rather than CPU/IO.
- Recurring, short-lived blocking episodes rather than one single long block.

## 3. Business Impact

- Sustained contention on hot rows (a popular trading pair's order book, a shared counter/sequence) caps the effective throughput of the entire feature regardless of available CPU/IO capacity.

## 4. Possible Root Causes

- Hot-row contention: many transactions updating the same small set of rows (a single market's order book summary row, a global sequence/counter table).
- Overly broad locking: a query or ORM taking a table-level lock where a row-level lock would suffice.
- Long transactions holding locks incidentally needed by many other short transactions.
- Missing indexes causing UPDATE/DELETE to lock more rows than necessary via a sequential scan under `SELECT ... FOR UPDATE`.

## 5. Investigation Strategy

1. Quantify the current scale of lock waiting across the whole instance, not just one session.
2. Identify which relations/rows are the most contended.
3. Check whether contention correlates with a small number of long-held locks or many short-lived ones.
4. Check for missing indexes on the contended table(s) that could be widening lock scope.

## 6. Prerequisites

- pg_monitor role membership.
- log_lock_waits enabled (via parameter group) recommended so contention is also visible in PostgreSQL logs/CloudWatch Logs, not just point-in-time snapshots.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_contention_scale_overview.sql`](scripts/01_contention_scale_overview.sql) -- Quantifies current lock-wait load across the instance as a starting scope check.
2. [`scripts/02_most_contended_relations.sql`](scripts/02_most_contended_relations.sql) -- Identifies which specific relations/locks currently have the most waiters.
3. [`scripts/03_ddl_style_locks.sql`](scripts/03_ddl_style_locks.sql) -- Checks specifically for stronger lock modes (ShareUpdateExclusive/ShareRowExclusive/AccessExclusive) contributing to contention.
4. [`scripts/04_missing_indexes_on_contended_tables.sql`](scripts/04_missing_indexes_on_contended_tables.sql) -- Checks index coverage on the most contended tables identified in script 02, since a missing index can widen lock scope under row-locking operations.

## 8. Interpretation Guide

- A small number of relations accounting for most contention narrows the fix to specific hot tables rather than a systemic issue.
- If contention is spread evenly across many unrelated tables, suspect a systemic cause (e.g. an ORM defaulting to SERIALIZABLE isolation, or missing indexes across the board) rather than one hot table.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Identify and resolve any single long-held blocking transaction contributing disproportionately (see blocked-queries).

**Short-term remediation** (hours to days):

- Add missing indexes so row-locking operations (`UPDATE`/`SELECT FOR UPDATE`) only lock the intended rows.
- Reduce transaction scope so locks are held for the minimum necessary time.
- Consider `SELECT ... FOR UPDATE SKIP LOCKED` for queue-like workloads where contention is expected and acceptable to skip rather than wait.

**Long-term engineering fix** (days to weeks):

- Redesign hot-row patterns (e.g. sharding a global counter, using an append-only ledger with periodic aggregation instead of updating one row per transaction).
- Introduce application-level backoff/retry with jitter for expected contention hot spots.

## 10. Production Safety

- All investigation scripts are read-only.
- Do not blindly add `NOWAIT`/`SKIP LOCKED` to existing queries without confirming the business logic can tolerate skipping a locked row.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Contention is traced to a fundamental data-model hot spot (e.g. one row representing a single trading pair's global state) -- this typically requires an application/schema redesign decision, escalate to database engineering and application architecture leadership.

## 12. Related Issues

- [blocked-queries](../blocked-queries/README.md)
- [transaction-contention](../transaction-contention/README.md)
- [missing-index-candidates](../../tables-and-indexes/missing-index-candidates/README.md)
