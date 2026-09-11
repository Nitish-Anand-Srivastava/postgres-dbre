# Locking and Concurrency

**Category:** `concurrency-and-locking`

This is the index for the `concurrency-and-locking/` category: every workflow
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
| [`blocked-queries`](blocked-queries/README.md) | One or more sessions are waiting on a lock held by another session, delaying query completion and, if the wait chain is long, threatening a broader slowdown or timeout cascade. |
| [`lock-contention`](lock-contention/README.md) | Broader, sustained lock contention across the workload (not just one isolated blocked session) -- many sessions repeatedly waiting on locks, degrading overall throughput and latency. |
| [`deadlocks`](deadlocks/README.md) | Two or more transactions are (or recently were) mutually waiting on locks held by each other, causing PostgreSQL's deadlock detector to abort one of them automatically. |
| [`long-running-transactions`](long-running-transactions/README.md) | A transaction has been open significantly longer than the workload's normal transaction duration, risking lock retention, vacuum horizon stalls, and increased rollback cost if it eventually fails. |
| [`idle-in-transaction`](idle-in-transaction/README.md) | Sessions holding an open transaction while sitting idle (not executing any statement) -- a specific and very common form of long-running-transaction typically caused by an application/connection-pool bug rather than a legitimate long operation. |
| [`transaction-contention`](transaction-contention/README.md) | A broader pattern of concurrent transactions repeatedly conflicting with each other -- not necessarily deadlocking or fully blocking, but serializing, retrying, or aborting (serialization failures under REPEATABLE READ/SERIALIZABLE) at a rate that measurably reduces throughput. |
| [`ddl-blocking`](ddl-blocking/README.md) | A DDL statement (ALTER TABLE, CREATE INDEX without CONCURRENTLY, VACUUM FULL, TRUNCATE) is holding or waiting for a strong lock (e.g. AccessExclusiveLock) that blocks a wide swath of normal application queries -- the classic 'one migration takes down the app' incident. |
| [`connection-contention`](connection-contention/README.md) | Sessions are waiting not on table/row locks but on connection-level or client-level resources -- for example, waiting for a connection pool slot, or waiting on Client wait events indicating the server is ready but the client/network side is slow to proceed. |

## Related Categories

- [`connections/connection-exhaustion`](../../connections/connection-exhaustion/README.md)
- [`connections/connection-pooling`](../../connections/connection-pooling/README.md)
- [`connections/idle-in-transaction`](../../connections/idle-in-transaction/README.md)
- [`incident-response/lock-storm`](../../incident-response/lock-storm/README.md)
- [`schema-changes/ddl-lock-investigation`](../../schema-changes/ddl-lock-investigation/README.md)
- [`schema-changes/safe-index-creation`](../../schema-changes/safe-index-creation/README.md)
- [`tables-and-indexes/missing-index-candidates`](../../tables-and-indexes/missing-index-candidates/README.md)
- [`transactions-and-xid/xid-wraparound-risk`](../../transactions-and-xid/xid-wraparound-risk/README.md)

Start with the workflow whose title most closely matches the symptom you are
investigating; if uncertain, `database-health/comprehensive-health-check`
and `incident-response/production-triage` both provide a broad first pass
that surfaces which specific workflow to open next.
