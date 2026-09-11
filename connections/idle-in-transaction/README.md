# Idle-in-Transaction (Connections View)

**Category:** Connection Management | **Workflow:** `connections/idle-in-transaction`

## 1. Problem Description

Connection-management-focused entry point for idle-in-transaction sessions; see concurrency-and-locking/idle-in-transaction for the full lock/concurrency-impact investigation of the same underlying sessions.

## 2. Typical Symptoms

- See concurrency-and-locking/idle-in-transaction.

## 3. Business Impact

- Beyond the lock/vacuum impact covered in concurrency-and-locking, idle-in-transaction sessions also consume a connection slot exactly as if they were doing useful work.

## 4. Possible Root Causes

- See concurrency-and-locking/idle-in-transaction.

## 5. Investigation Strategy

1. List idle-in-transaction sessions and their connection-slot impact.
2. Cross-reference with concurrency-and-locking/idle-in-transaction for lock impact.

## 6. Prerequisites

- pg_monitor role membership.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_idle_in_transaction_sessions.sql`](scripts/01_idle_in_transaction_sessions.sql) -- Lists idle-in-transaction sessions, viewed here for their connection-slot consumption impact.

## 8. Interpretation Guide

- Treat any idle-in-transaction session as both a connection-budget concern and a lock/vacuum concern simultaneously.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- See concurrency-and-locking/idle-in-transaction.

**Short-term remediation** (hours to days):

- Set idle_in_transaction_session_timeout at the role/database level.

**Long-term engineering fix** (days to weeks):

- See concurrency-and-locking/idle-in-transaction.

## 10. Production Safety

- Read-only.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- See concurrency-and-locking/idle-in-transaction.

## 12. Related Issues

- [idle-in-transaction](../../concurrency-and-locking/idle-in-transaction/README.md)
- [connection-exhaustion](../connection-exhaustion/README.md)
