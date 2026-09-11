# Table and Index Health

**Category:** `tables-and-indexes`

This is the index for the `tables-and-indexes/` category: every workflow
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
| [`unused-indexes`](unused-indexes/README.md) | Identifies indexes that appear to receive zero or negligible scans, representing pure write-amplification and storage cost with no measured query benefit -- while explicitly guarding against premature removal. |
| [`duplicate-indexes`](duplicate-indexes/README.md) | Identifies structurally identical or fully redundant indexes on the same table -- pure waste with no tradeoff, unlike unused-indexes which requires judgment about rare query patterns. |
| [`missing-index-candidates`](missing-index-candidates/README.md) | Identifies tables/query patterns that would likely benefit from a new index -- unindexed foreign keys, and tables with heavy sequential scans relative to their size. |
| [`sequential-scan-investigation`](sequential-scan-investigation/README.md) | Deep-dive investigation into why a specific table or query is using a sequential scan instead of an expected index scan. |
| [`index-bloat`](index-bloat/README.md) | Table/index-health-focused entry point for index bloat investigation; see vacuum-and-autovacuum/index-bloat for the vacuum-lifecycle perspective on the same underlying issue. |
| [`table-bloat`](table-bloat/README.md) | Table/index-health-focused entry point for table bloat investigation; see vacuum-and-autovacuum/table-bloat for the vacuum-lifecycle perspective on the same underlying issue. |
| [`invalid-indexes`](invalid-indexes/README.md) | Finds indexes left in an INVALID state after a failed CREATE INDEX CONCURRENTLY or REINDEX CONCURRENTLY -- unused by the planner, but still consuming storage and write overhead until removed and, if needed, rebuilt. |
| [`large-tables`](large-tables/README.md) | Routine inventory of the largest tables/indexes in the database, used as a starting point for capacity planning, partitioning, and archiving decisions. |
| [`rapidly-growing-tables`](rapidly-growing-tables/README.md) | Identifies which tables are growing fastest (not just which are currently largest), the more actionable signal for proactive capacity planning, partitioning, and archiving prioritization. |
| [`table-access-patterns`](table-access-patterns/README.md) | Characterizes how a table is actually accessed (read-heavy vs write-heavy, sequential vs index-driven, hot vs cold) to inform indexing, partitioning, and caching decisions. |

## Related Categories

- [`automation/growth-monitoring`](../../automation/growth-monitoring/README.md)
- [`maintenance`](../../maintenance/README.md)
- [`performance/query-regression`](../../performance/query-regression/README.md)
- [`query-optimization/analyze-query-plan`](../../query-optimization/analyze-query-plan/README.md)
- [`schema-changes/concurrent-index-build`](../../schema-changes/concurrent-index-build/README.md)
- [`schema-changes/drop-index-safely`](../../schema-changes/drop-index-safely/README.md)
- [`schema-changes/failed-index-build`](../../schema-changes/failed-index-build/README.md)
- [`storage-and-capacity/capacity-forecasting`](../../storage-and-capacity/capacity-forecasting/README.md)
- [`vacuum-and-autovacuum/autovacuum-not-keeping-up`](../../vacuum-and-autovacuum/autovacuum-not-keeping-up/README.md)
- [`vacuum-and-autovacuum/index-bloat`](../../vacuum-and-autovacuum/index-bloat/README.md)
- [`vacuum-and-autovacuum/table-bloat`](../../vacuum-and-autovacuum/table-bloat/README.md)

Start with the workflow whose title most closely matches the symptom you are
investigating; if uncertain, `database-health/comprehensive-health-check`
and `incident-response/production-triage` both provide a broad first pass
that surfaces which specific workflow to open next.
