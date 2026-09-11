# Prepared (Two-Phase-Commit) Transactions

**Category:** Transaction ID (XID) Wraparound and Transaction Management | **Workflow:** `transactions-and-xid/prepared-transactions`

## 1. Problem Description

Investigates outstanding PREPARE TRANSACTION entries left in a non-committed, non-rolled-back state, which hold locks and pin the vacuum horizon indefinitely until explicitly resolved.

## 2. Typical Symptoms

- Non-empty pg_prepared_xacts result set.
- Vacuum horizon stalled with no ordinary session identified as the cause.

## 3. Business Impact

- An orphaned prepared transaction behaves like a permanently open transaction -- it does not time out on its own and will pin the vacuum horizon indefinitely, directly contributing to wraparound risk.

## 4. Possible Root Causes

- A distributed transaction coordinator (XA-style ORM/middleware, a manually issued PREPARE TRANSACTION) crashed or lost connectivity before issuing the matching COMMIT PREPARED/ROLLBACK PREPARED.
- max_prepared_transactions configured and in use by a framework the application team may not be fully aware of.

## 5. Investigation Strategy

1. List all currently prepared transactions and their age.
2. Identify the owning application/coordinator for any found.
3. Coordinate the correct resolution (commit or rollback) with that system -- do not guess.

## 6. Prerequisites

- pg_monitor role membership for the read-only check; coordination with the owning application team before resolving any entry.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_list_prepared_transactions.sql`](scripts/01_list_prepared_transactions.sql) -- Lists all outstanding prepared (two-phase-commit) transactions and their age.

## 8. Interpretation Guide

- Any prepared transaction older than the coordinator's expected resolution window (typically seconds) is almost certainly orphaned, not legitimately in-flight.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Confirm with the owning team whether to COMMIT PREPARED or ROLLBACK PREPARED the specific `gid` -- this determines whether its changes are kept or discarded, which can matter for financial consistency across the distributed transaction.

**Short-term remediation** (hours to days):

- Audit why the coordinator failed to resolve it and fix the underlying reliability gap.

**Long-term engineering fix** (days to weeks):

- Reassess whether two-phase commit is actually required for the use case; many distributed-consistency patterns can be achieved with an outbox/saga pattern instead, avoiding this class of risk entirely.

## 10. Production Safety

- The listing script is read-only.
- Resolving a prepared transaction is a data-affecting decision (commit keeps its changes, rollback discards them) -- never resolve one without confirming the correct outcome with its owning system.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Any prepared transaction is found and its owning system cannot be identified -- escalate to database engineering leadership before taking any action.

## 12. Related Issues

- [xid-wraparound-risk](../xid-wraparound-risk/README.md)
- [oldest-transactions](../oldest-transactions/README.md)
