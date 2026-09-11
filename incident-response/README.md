# Incident Response

**Category:** `incident-response`

This is the index for the `incident-response/` category: every workflow
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
| [`database-unavailable`](database-unavailable/README.md) | Services report that the database is down: connections are refused, time out, or fail instantly, and trading, deposits, withdrawals and settlement are failing across the board. This workflow covers the first five minutes of that incident -- establishing whether the database is genuinely unavailable, unavailable only to some callers, or completely healthy behind a broken connectivity or pooling layer, before anybody reaches for a failover or a restart. |
| [`sudden-latency-spike`](sudden-latency-spike/README.md) | Database response times jumped sharply and recently -- p99 order placement, balance reads or ledger writes went from milliseconds to seconds within minutes -- without any obvious outage. This workflow is the fast triage that separates the four candidate causes (blocking, a plan or workload change, resource saturation, or pressure from checkpoint/IO/temp activity) quickly enough to act on the answer, rather than the deep single-query analysis that belongs in the performance category. |
| [`high-cpu`](high-cpu/README.md) | CloudWatch is alarming on CPUUtilization for the writer or a reader and somebody needs an answer in the next five minutes. This is the rapid triage version: establish whether the CPU is doing useful work, find the sessions responsible, and decide what to cut. The deep-dive analysis of why a query is expensive belongs in `performance/high-cpu`; do not start there while an alarm is firing. |
| [`connection-exhaustion`](connection-exhaustion/README.md) | New connections are being refused with `FATAL: sorry, too many clients already` while existing sessions continue to work. This is the rapid triage version: find out who is holding the slots, reclaim enough of them to restore service, and identify the owning service so the slots do not simply refill. The structural work of pool sizing and connection budgeting belongs in `connections/connection-exhaustion`. |
| [`lock-storm`](lock-storm/README.md) | A large number of sessions are simultaneously waiting on locks, so the database is up and has plenty of CPU but is effectively frozen for the affected tables. Order writes, balance updates and ledger inserts queue behind a wait graph that is usually rooted in one or two sessions. This workflow finds that root within minutes and clears it safely. |
| [`runaway-query`](runaway-query/README.md) | A single query is consuming a disproportionate share of the instance's resources -- running for minutes on an OLTP path, spilling gigabytes of temp files, holding locks that other sessions need, or all three. This workflow identifies it precisely, quantifies what it is actually costing, and stops it with the smallest possible intervention. |
| [`application-timeouts`](application-timeouts/README.md) | Services are reporting database timeouts -- statement timeouts, pool-acquisition timeouts, or client-side deadline expiry -- and the question is whether the database is actually slow, or whether a timeout is set too aggressively, or whether the bottleneck is in the pooler or the network. This workflow answers that question quickly, because the three causes have completely different fixes and only one of them is a database problem. |
| [`post-deployment-incident`](post-deployment-incident/README.md) | Something broke immediately after a release, and the question is whether the deployment caused it and whether to roll back now. Time pressure here is extreme and the bias should be toward rollback -- but a schema migration may have made rollback unsafe, so this workflow establishes what the deployment actually did to the database before that decision is made. |
| [`production-triage`](production-triage/README.md) | The single checklist to run, start to finish, during ANY production incident on this cluster before deciding what to do next. Ten read-only scripts, in a fixed order, that take a complete picture of the database in a few minutes: cluster role, session load, wait events, blocking, long queries, long transactions, connection headroom, top statements, vacuum state, and storage. Every other workflow in this category answers a specific question; this one tells you which question to ask, and leaves behind the snapshot that the post-incident review will need. |

## Related Categories

- [`concurrency-and-locking/blocked-queries`](../../concurrency-and-locking/blocked-queries/README.md)
- [`connections/connection-exhaustion`](../../connections/connection-exhaustion/README.md)
- [`database-health/comprehensive-health-check`](../../database-health/comprehensive-health-check/README.md)
- [`disaster-recovery`](../../disaster-recovery/README.md)
- [`performance/high-cpu`](../../performance/high-cpu/README.md)
- [`replication-and-ha/failover-investigation`](../../replication-and-ha/failover-investigation/README.md)
- [`schema-changes/failed-index-build`](../../schema-changes/failed-index-build/README.md)

Start with the workflow whose title most closely matches the symptom you are
investigating; if uncertain, `database-health/comprehensive-health-check`
and `incident-response/production-triage` both provide a broad first pass
that surfaces which specific workflow to open next.
