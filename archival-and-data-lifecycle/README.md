# Archiving and Data Lifecycle

**Category:** `archival-and-data-lifecycle`

This is the index for the `archival-and-data-lifecycle/` category: every workflow
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
| [`investigate-archiving-candidate`](investigate-archiving-candidate/README.md) | Determines whether a table is a good candidate for archiving/retention-based purging, and establishes the data required (growth rate, access pattern, regulatory retention requirements) to plan a safe archive-large-table migration. |
| [`archive-large-table`](archive-large-table/README.md) | A comprehensive Staff DBA runbook for safely archiving historical data out of a very large, high-throughput production table -- covering boundary selection, batch export/migration, batch deletion without long locks or WAL spikes, partition-based detach/drop shortcuts where applicable, and validation before any destructive step. |
| [`archive-partition`](archive-partition/README.md) | For tables already partitioned by a time/range-compatible key, archives historical data by detaching whole partitions instead of row-by-row deletion -- dramatically faster and lower-risk than archive-large-table's batched-DELETE path. |
| [`purge-old-data`](purge-old-data/README.md) | Investigates and safely executes deletion of old data that does NOT need to be retained/archived at all (e.g. expired sessions, ephemeral cache-like rows, expired idempotency keys) -- distinct from archive-large-table, where the data must be preserved in cold storage first. |
| [`retention-policy`](retention-policy/README.md) | Establishes and documents durable retention policy per table/data category, distinguishing compliance-mandated retention (must archive, never purge) from purely operational ephemeral data (safe to purge), and tracks which tables have an active, working enforcement mechanism. |
| [`archive-validation`](archive-validation/README.md) | Standalone, repeatable validation procedures to confirm an existing archive (already exported, whether recently or long ago) remains complete, queryable, and restorable -- distinct from the one-time validation performed during an active archive-large-table migration. |

## Related Categories

- [`partitioning/partition-maintenance`](../../partitioning/partition-maintenance/README.md)

Start with the workflow whose title most closely matches the symptom you are
investigating; if uncertain, `database-health/comprehensive-health-check`
and `incident-response/production-triage` both provide a broad first pass
that surfaces which specific workflow to open next.
