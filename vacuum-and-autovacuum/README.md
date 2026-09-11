# Vacuum and Autovacuum

**Category:** `vacuum-and-autovacuum`

This is the index for the `vacuum-and-autovacuum/` category: every workflow
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
| [`autovacuum-not-keeping-up`](autovacuum-not-keeping-up/README.md) | Autovacuum is running but dead tuples / table bloat are growing faster than autovacuum can clean them up, degrading query performance and increasing storage over time. |
| [`vacuum-progress`](vacuum-progress/README.md) | Tracks the real-time progress of an in-flight VACUUM (manual or autovacuum) operation, to answer 'how much longer will this take' and 'is it stuck'. |
| [`dead-tuples`](dead-tuples/README.md) | Investigates elevated dead tuple counts/ratios across tables -- the direct precursor to bloat, degraded index efficiency, and increased I/O, and the primary metric autovacuum acts on. |
| [`table-bloat`](table-bloat/README.md) | Investigates physical table bloat -- disk space consumed by dead/reusable tuple space that has not been returned to the OS or reused efficiently, distinct from the logical dead-tuple count itself. |
| [`index-bloat`](index-bloat/README.md) | Investigates physical bloat specifically within indexes, which accumulates independently of table bloat and directly slows down index scans and increases index-storage footprint. |
| [`vacuum-blocked`](vacuum-blocked/README.md) | Autovacuum or a manual VACUUM is unable to start or make progress on a specific table due to a lock conflict or a long-running transaction holding back its required snapshot horizon. |
| [`emergency-autovacuum`](emergency-autovacuum/README.md) | A table has crossed autovacuum_freeze_max_age and is now being vacuumed in mandatory 'anti-wraparound' mode (or has crossed vacuum_failsafe_age and is in accelerated failsafe mode), which cannot be cancelled without directly increasing wraparound risk. |
| [`analyze-statistics`](analyze-statistics/README.md) | Investigates whether planner statistics are fresh and representative, distinct from vacuum's tuple-cleanup role -- ANALYZE (whether run manually, via autoanalyze, or as part of autovacuum) is what keeps the query planner's row/selectivity estimates accurate. |

## Related Categories

- [`concurrency-and-locking/long-running-transactions`](../../concurrency-and-locking/long-running-transactions/README.md)
- [`maintenance`](../../maintenance/README.md)
- [`performance/query-regression`](../../performance/query-regression/README.md)
- [`query-optimization/stale-statistics`](../../query-optimization/stale-statistics/README.md)
- [`schema-changes/concurrent-index-build`](../../schema-changes/concurrent-index-build/README.md)
- [`tables-and-indexes/index-bloat`](../../tables-and-indexes/index-bloat/README.md)
- [`transactions-and-xid/xid-wraparound-risk`](../../transactions-and-xid/xid-wraparound-risk/README.md)

Start with the workflow whose title most closely matches the symptom you are
investigating; if uncertain, `database-health/comprehensive-health-check`
and `incident-response/production-triage` both provide a broad first pass
that surfaces which specific workflow to open next.
