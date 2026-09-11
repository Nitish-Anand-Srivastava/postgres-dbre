# 02_safe_handling_during_emergency_vacuum

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `02_safe_handling_during_emergency_vacuum.md` |
| Purpose | Manual guidance for what to do (and not do) while an anti-wraparound/failsafe vacuum is in progress. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only (the query reads/writes state that only exists or is meaningful on the writer) |
| Safety | DOCUMENTATION -- no SQL executed by this file itself |
| Expected impact | None from this file directly. |
| Required privileges | N/A |
| Prerequisites | An anti-wraparound/failsafe vacuum confirmed via script 01. |
| Execution order | Step 02 of workflow `vacuum-and-autovacuum/emergency-autovacuum` |
| Related scripts | ../../transactions-and-xid/xid-wraparound-risk/README.md |

## How to interpret / use this runbook

Read this in full before taking any action while an emergency vacuum is in progress -- the single most important guidance is to let it run.

---

## Do

- Monitor progress via `pg_stat_progress_vacuum` (see script 01) every few minutes.
- Resolve any long-running transaction or lock conflict that could be preventing the vacuum from completing (see concurrency-and-locking/long-running-transactions and vacuum-and-autovacuum/vacuum-blocked).
- Communicate expected duration to stakeholders based on heap_blks_scanned progress rate, since this vacuum may consume more visible I/O/CPU than routine background vacuuming.

## Do NOT

- Do NOT run `SELECT pg_cancel_backend(<autovacuum_worker_pid>);` against this worker -- cancelling it does not remove the underlying wraparound risk, it only delays the inevitable next attempt while the risk continues to grow.
- Do NOT disable autovacuum (globally or per-table) to 'stop the noise' -- this is the single worst possible action during an active wraparound-risk event.
- Do NOT attempt a `VACUUM FULL` instead, hoping it will be faster -- it takes an AccessExclusiveLock for a full table rewrite and is not needed; the running anti-wraparound vacuum is already the correct, safe operation.
