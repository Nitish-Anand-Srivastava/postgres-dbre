# Query Optimization

**Category:** `query-optimization`

This is the index for the `query-optimization/` category: every workflow
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
| [`analyze-query-plan`](analyze-query-plan/README.md) | The structured method for taking a specific slow statement on an Aurora PostgreSQL 17 exchange database and understanding why the planner chose the plan it did. It starts from evidence that costs nothing (pg_stat_statements aggregates, table and index statistics, planner configuration), and only then decides whether capturing a real execution profile is justified -- because EXPLAIN is free and EXPLAIN ANALYZE actually runs the statement, with every consequence that implies on a production order book. |
| [`nested-loop-problems`](nested-loop-problems/README.md) | A nested loop join re-executes the inner side once per outer row. That is the fastest possible strategy when the outer side really does produce a handful of rows and the inner side has a supporting index -- and it is the single most destructive plan shape in PostgreSQL when the planner underestimates the outer row count. This workflow finds statements whose block-access-per-row profile is characteristic of a runaway nested loop, identifies the estimation error or missing index behind it, and guards the decision to confirm it with a real execution profile. |
| [`hash-join-analysis`](hash-join-analysis/README.md) | A hash join builds an in-memory hash table from one input and probes it with the other. It is the right strategy for joining large row sets and is what an exchange's reconciliation, settlement, and reporting queries should normally use -- provided the hash table fits in memory. When it does not, PostgreSQL partitions the join into batches spilled to temporary files, and the same query silently becomes several times slower. This workflow finds hash joins that are spilling, determines whether the cause is memory sizing or a bad row estimate, and guards the memory experiment. |
| [`merge-join-analysis`](merge-join-analysis/README.md) | A merge join walks two inputs in sorted order simultaneously. When both inputs already arrive sorted -- typically from an index scan on the join key -- it is extremely efficient and memory-light, which makes it the ideal strategy for large time-ordered joins such as trades to fills or ledger entries to settlement batches. When the inputs are not already sorted, PostgreSQL must sort them first, and those sorts can spill to disk and dominate the query's cost. This workflow determines which situation you are in and what to do about it. |
| [`cardinality-estimation`](cardinality-estimation/README.md) | Almost every bad plan in PostgreSQL is a bad estimate wearing a costume. The planner chooses join strategies, join order, and access paths from its prediction of how many rows each node will produce; when that prediction is wrong by an order of magnitude, the resulting plan is wrong no matter how well the engine executes it. This workflow examines what the planner actually believes about an exchange's data -- distinct values, skew, null fractions, correlation, and the multi-column dependencies it cannot see by default -- and shows how to correct it. |
| [`stale-statistics`](stale-statistics/README.md) | Planner statistics are a snapshot of the data taken by the last ANALYZE. When a table changes substantially after that snapshot -- a backfill, a migration, a surge of new trades during a volatility event, a bulk purge -- the planner keeps making decisions from a picture of the data that no longer exists. This workflow finds tables whose statistics have drifted, explains why autoanalyze did not catch them, and provides the guarded runbook for refreshing them safely. |
| [`sort-spills`](sort-spills/README.md) | When a sort does not fit in work_mem, PostgreSQL switches from an in-memory quicksort to an external merge sort that writes runs to temporary files and merges them back. The query still returns correct results, silently, several times slower. On an exchange this hits ORDER BY on trade and order history, window functions over ledger entries, DISTINCT and GROUP BY on large result sets, and the sorts that feed merge joins. This workflow finds the spilling statements, decides whether the answer is memory, an index, or a smaller input, and guards the memory experiment. |
| [`temp-file-investigation`](temp-file-investigation/README.md) | Temporary files are PostgreSQL's overflow mechanism: any operation that exceeds its memory budget -- a sort, a hash join, a hash aggregate, a materialized CTE, a large cursor -- writes the excess to local instance storage. This workflow is the instance-level view: how much temporary file volume exists, which statements produce it, which sessions are producing it right now, and whether the configuration makes it visible at all. It is where an unexplained I/O or storage symptom is traced back to a specific statement. |
| [`inefficient-index-usage`](inefficient-index-usage/README.md) | An index can be present, valid, and still be the wrong answer: the planner may ignore it, it may be scanned but discard most of what it reads, it may duplicate another index, or it may never have been used at all while still taxing every insert on the order path. This workflow separates those cases using the catalog and the index statistics, so index changes on an exchange's hot tables are made from evidence rather than from intuition. |
| [`query-plan-regression`](query-plan-regression/README.md) | A statement that was fast yesterday is slow today, and its text has not changed. The plan did. This workflow is built around comparison: it finds statements whose latency distribution has shifted, enumerates the things that can change a plan without changing a query (statistics, data volume, index state, configuration, parameter values, cached generic plans), and provides the runbook for capturing plan baselines so the next regression is diagnosed by comparison rather than by reconstruction. |

## Related Categories

- [`database-health/capacity-health-check`](../../database-health/capacity-health-check/README.md)
- [`database-health/post-deployment-check`](../../database-health/post-deployment-check/README.md)
- [`performance/high-iops`](../../performance/high-iops/README.md)
- [`performance/performance-after-deployment`](../../performance/performance-after-deployment/README.md)
- [`performance/query-regression`](../../performance/query-regression/README.md)
- [`performance/slow-queries`](../../performance/slow-queries/README.md)
- [`tables-and-indexes/duplicate-indexes`](../../tables-and-indexes/duplicate-indexes/README.md)
- [`tables-and-indexes/missing-index-candidates`](../../tables-and-indexes/missing-index-candidates/README.md)
- [`tables-and-indexes/sequential-scan-investigation`](../../tables-and-indexes/sequential-scan-investigation/README.md)
- [`tables-and-indexes/unused-indexes`](../../tables-and-indexes/unused-indexes/README.md)
- [`vacuum-and-autovacuum/analyze-statistics`](../../vacuum-and-autovacuum/analyze-statistics/README.md)

Start with the workflow whose title most closely matches the symptom you are
investigating; if uncertain, `database-health/comprehensive-health-check`
and `incident-response/production-triage` both provide a broad first pass
that surfaces which specific workflow to open next.
