# Transaction Contention

**Category:** Locking and Concurrency | **Workflow:** `concurrency-and-locking/transaction-contention`

## 1. Problem Description

A broader pattern of concurrent transactions repeatedly conflicting with each other -- not necessarily deadlocking or fully blocking, but serializing, retrying, or aborting (serialization failures under REPEATABLE READ/SERIALIZABLE) at a rate that measurably reduces throughput.

## 2. Typical Symptoms

- Rising serialization_failure (SQLSTATE 40001) errors at the application layer.
- Throughput lower than expected despite adequate CPU/IO/connection headroom.
- Application-level retry counters increasing for specific transaction types.

## 3. Business Impact

- Serialization failures on financial transactions (e.g. a balance check-then-update pattern) that are not retried correctly can silently drop a legitimate operation.

## 4. Possible Root Causes

- Use of SERIALIZABLE or REPEATABLE READ isolation for hot-row workloads without corresponding retry logic.
- A check-then-act pattern (SELECT balance, then UPDATE) racing across concurrent requests for the same account without row-level locking (`SELECT ... FOR UPDATE`).
- Excessive concurrency targeting the same narrow set of rows (see the hot-row-contention guidance in the root README).

## 5. Investigation Strategy

1. Confirm the isolation levels in use for the affected transaction type.
2. Check current lock wait patterns on the specific rows/tables involved.
3. Check pg_stat_database for rollback rate as a proxy for contention-driven aborts.
4. Review whether the application uses explicit row locking (`FOR UPDATE`) or optimistic concurrency (version column) for the affected pattern.

## 6. Prerequisites

- pg_monitor role membership.
- Access to the application's transaction isolation-level configuration.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_rollback_rate_by_database.sql`](scripts/01_rollback_rate_by_database.sql) -- Checks the transaction rollback rate per database as a proxy for contention-driven aborts (including serialization failures).
2. [`scripts/02_current_isolation_levels.sql`](scripts/02_current_isolation_levels.sql) -- Shows the transaction isolation level in use by each currently active session.
3. [`scripts/03_contended_rows.sql`](scripts/03_contended_rows.sql) -- Identifies the specific rows/relations currently experiencing the most lock waiting.

## 8. Interpretation Guide

- A high xact_rollback rate concentrated in a specific time window/workload, combined with confirmed non-default isolation levels, points directly at serialization-failure-driven contention rather than a business-logic bug.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If a specific operation is failing at a high rate, confirm the application is retrying serialization failures with backoff; if not, this is an urgent application fix.

**Short-term remediation** (hours to days):

- Switch the affected pattern to explicit `SELECT ... FOR UPDATE` with READ COMMITTED isolation if strict serializability is not actually required, since READ COMMITTED with row locks avoids most serialization failures for simple check-then-act patterns.
- Add `SET LOCAL lock_timeout` so contending transactions fail fast and retry rather than queue.

**Long-term engineering fix** (days to weeks):

- Redesign hot financial-entity update patterns to use optimistic concurrency (version/updated_at column with a conditional UPDATE) or an append-only ledger with periodic aggregation instead of repeated in-place updates.

## 10. Production Safety

- Investigation scripts are read-only.
- Isolation-level changes must be tested thoroughly against the specific business invariants they protect before rollout.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- The contended pattern is a core financial invariant (balance, position) and a fix requires an application/data-model change -- escalate to database engineering and the owning application team jointly.

## 12. Related Issues

- [lock-contention](../lock-contention/README.md)
- [deadlocks](../deadlocks/README.md)
