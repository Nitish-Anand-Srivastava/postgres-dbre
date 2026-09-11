# Partitioning

**Category:** `partitioning`

This is the index for the `partitioning/` category: every workflow
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
| [`investigate-partitioning-candidate`](investigate-partitioning-candidate/README.md) | Determines whether a given table is actually a good candidate for partitioning before committing to the significant engineering effort of partition-existing-large-table. |
| [`partition-existing-large-table`](partition-existing-large-table/README.md) | A comprehensive, realistic Staff DBA runbook for migrating an existing, already-large, in-production table to a native PostgreSQL declarative-partitioned structure with minimal downtime and controlled risk. This is deliberately NOT a single `ALTER TABLE ... PARTITION BY` -- PostgreSQL does not support converting an existing table in place; a new partitioned table must be built alongside it, backfilled, kept in sync, validated, and cut over. |
| [`partition-maintenance`](partition-maintenance/README.md) | Ongoing operational maintenance for an already-partitioned table: creating future partitions ahead of need, detaching/archiving old ones, and keeping indexes/constraints consistent across all partitions. |
| [`partition-pruning`](partition-pruning/README.md) | Investigates whether queries against a partitioned table are actually benefiting from partition pruning (scanning only relevant partitions) or are unexpectedly scanning all partitions. |
| [`missing-partitions`](missing-partitions/README.md) | A partitioned table has received (or is about to receive) data for a period/value that has no matching partition, either failing the insert or silently routing to an unintended DEFAULT partition. |
| [`partition-skew`](partition-skew/README.md) | Investigates uneven data distribution across partitions -- some partitions much larger or more heavily accessed than others -- which undermines the maintenance and performance benefits partitioning is meant to provide. |
| [`partition-performance`](partition-performance/README.md) | Investigates whether partitioning is delivering its expected performance benefits (or introducing unexpected regressions) for query, vacuum, and DML performance on the partitioned table as a whole. |

## Related Categories

- [`automation`](../../automation/README.md)
- [`query-optimization/analyze-query-plan`](../../query-optimization/analyze-query-plan/README.md)
- [`schema-changes/large-table-ddl`](../../schema-changes/large-table-ddl/README.md)
- [`storage-and-capacity/table-growth`](../../storage-and-capacity/table-growth/README.md)

Start with the workflow whose title most closely matches the symptom you are
investigating; if uncertain, `database-health/comprehensive-health-check`
and `incident-response/production-triage` both provide a broad first pass
that surfaces which specific workflow to open next.
