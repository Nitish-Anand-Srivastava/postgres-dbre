# Oldest Open Transactions

**Category:** Transaction ID (XID) Wraparound and Transaction Management | **Workflow:** `transactions-and-xid/oldest-transactions`

## 1. Problem Description

Identifies the single oldest currently-open transaction(s) cluster-wide, since the oldest open transaction determines the effective vacuum cleanup horizon for every database, regardless of how healthy any individual table's autovacuum schedule is.

## 2. Typical Symptoms

- Vacuum unable to advance relfrozenxid on multiple, otherwise-unrelated tables simultaneously.
- n_dead_tup climbing across many tables at once rather than one specific hot table.

## 3. Business Impact

- A single old transaction can silently degrade vacuum effectiveness across the entire database, making this one of the highest-leverage single checks in routine health monitoring.

## 4. Possible Root Causes

- See concurrency-and-locking/long-running-transactions and idle-in-transaction for the underlying causes -- this workflow is the XID-focused lens on the same underlying sessions.

## 5. Investigation Strategy

1. List the oldest open transactions cluster-wide by backend_xmin/xact_start.
2. Cross-reference with locks held and idle-in-transaction state.
3. Resolve per the concurrency-and-locking workflows.

## 6. Prerequisites

- pg_monitor role membership.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_oldest_transactions_cluster_wide.sql`](scripts/01_oldest_transactions_cluster_wide.sql) -- Lists the oldest currently open transactions across the instance, ranked by age.
2. [`scripts/02_backend_xmin_horizon.sql`](scripts/02_backend_xmin_horizon.sql) -- Shows each backend's reported xmin, the actual value that determines the vacuum cleanup horizon (distinct from xact_start wall-clock age).

## 8. Interpretation Guide

- The oldest transaction's backend_xmin -- not just its xact_start wall-clock age -- is what actually pins the vacuum horizon; a transaction open for a long wall-clock time in an otherwise idle system is lower risk than a shorter-but-XID-heavy window during a traffic spike.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Resolve the identified oldest transaction per concurrency-and-locking/long-running-transactions or idle-in-transaction.

**Short-term remediation** (hours to days):

- Set idle_in_transaction_session_timeout and statement_timeout to bound future exposure.

**Long-term engineering fix** (days to weeks):

- Add oldest-transaction-age to the same automated monitoring as XID age itself (automation/xid-monitoring), since the two are directly linked.

## 10. Production Safety

- All scripts are read-only.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Oldest transaction age approaches a significant fraction of autovacuum_freeze_max_age -- escalate to xid-wraparound-risk.

## 12. Related Issues

- [xid-wraparound-risk](../xid-wraparound-risk/README.md)
- [long-running-transactions](../../concurrency-and-locking/long-running-transactions/README.md)
