# Transaction ID (XID) Wraparound and Transaction Management

**Category:** `transactions-and-xid`

This is the index for the `transactions-and-xid/` category: every workflow
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
| [`xid-wraparound-risk`](xid-wraparound-risk/README.md) | PostgreSQL transaction IDs are a finite 32-bit counter. If the oldest unfrozen transaction ID in any database is allowed to age past ~2.1 billion transactions without being frozen by vacuum, PostgreSQL will refuse new transactions cluster-wide to protect data integrity (a full outage that requires single-user-mode recovery to resolve). This workflow is the comprehensive, staff-level investigation and prevention runbook for that risk. |
| [`transaction-age`](transaction-age/README.md) | Routine, lower-urgency monitoring of transaction ID age across databases and tables -- the proactive counterpart to xid-wraparound-risk, intended for regular health checks rather than active-incident response. |
| [`oldest-transactions`](oldest-transactions/README.md) | Identifies the single oldest currently-open transaction(s) cluster-wide, since the oldest open transaction determines the effective vacuum cleanup horizon for every database, regardless of how healthy any individual table's autovacuum schedule is. |
| [`prepared-transactions`](prepared-transactions/README.md) | Investigates outstanding PREPARE TRANSACTION entries left in a non-committed, non-rolled-back state, which hold locks and pin the vacuum horizon indefinitely until explicitly resolved. |
| [`multixact-risk`](multixact-risk/README.md) | Investigates the independent multixact ID wraparound horizon, driven by row-level locking (SELECT ... FOR UPDATE/SHARE, foreign key existence checks) rather than plain write volume -- easy to overlook because standard XID age can look completely healthy while multixact age is not. |

## Related Categories

- [`automation/xid-monitoring`](../../automation/xid-monitoring/README.md)
- [`concurrency-and-locking/lock-contention`](../../concurrency-and-locking/lock-contention/README.md)
- [`concurrency-and-locking/long-running-transactions`](../../concurrency-and-locking/long-running-transactions/README.md)
- [`vacuum-and-autovacuum/autovacuum-not-keeping-up`](../../vacuum-and-autovacuum/autovacuum-not-keeping-up/README.md)
- [`vacuum-and-autovacuum/emergency-autovacuum`](../../vacuum-and-autovacuum/emergency-autovacuum/README.md)

Start with the workflow whose title most closely matches the symptom you are
investigating; if uncertain, `database-health/comprehensive-health-check`
and `incident-response/production-triage` both provide a broad first pass
that surfaces which specific workflow to open next.
