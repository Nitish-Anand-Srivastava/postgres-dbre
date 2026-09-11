# Hash Join Analysis

**Category:** Query Optimization | **Workflow:** `query-optimization/hash-join-analysis`

## 1. Problem Description

A hash join builds an in-memory hash table from one input and probes it with the other. It is the right strategy for joining large row sets and is what an exchange's reconciliation, settlement, and reporting queries should normally use -- provided the hash table fits in memory. When it does not, PostgreSQL partitions the join into batches spilled to temporary files, and the same query silently becomes several times slower. This workflow finds hash joins that are spilling, determines whether the cause is memory sizing or a bad row estimate, and guards the memory experiment.

## 2. Typical Symptoms

- Temporary file volume rising on the instance without any obvious change in the workload.
- A reporting, reconciliation, or settlement query whose runtime has grown disproportionately as trade and ledger volumes grew.
- An EXPLAIN ANALYZE plan showing a Hash node with Batches greater than 1, or with a Memory Usage figure close to the work_mem limit.
- Query latency that improves markedly in a session where work_mem was raised, confirming a memory-bound rather than plan-bound problem.

## 3. Business Impact

- A spilling hash join writes and re-reads its entire build input through temporary files on local instance storage, turning a memory-speed operation into an I/O-bound one and multiplying runtime several times over.
- Month-end reconciliation and regulatory reporting queries are the usual victims on an exchange, and they run against deadlines where a multiplied runtime becomes a compliance risk rather than a performance annoyance.
- Temporary files consume finite local instance storage; several large concurrent spills can exhaust it and cause unrelated queries to fail outright.

## 4. Possible Root Causes

- work_mem too small for the size of the build input -- the most common and most directly fixable cause.
- A row underestimate on the build side, so the planner sized the hash table for a fraction of the rows that actually arrive.
- The planner choosing the larger relation as the build input because its estimate said it was smaller.
- Parallel query multiplying memory demand: each worker gets its own work_mem allocation for its own hash table.
- hash_mem_multiplier left at its default when the workload is dominated by a few large hash joins that could safely be given more memory than sorts get.
- A genuinely enormous join that no reasonable work_mem can hold, where the correct answer is to reduce the input (better predicates, pre-aggregation, partition pruning) rather than to add memory.

## 5. Investigation Strategy

1. Identify statements writing the most temporary blocks -- hash spills and sort spills both surface here, and the plan later tells you which.
2. Quantify the cluster-wide temporary file trend to judge whether this is a growing systemic issue or one bad query.
3. Review work_mem, hash_mem_multiplier, and the parallel worker settings that jointly determine how much memory a hash join can actually use.
4. Check statistics freshness on the joined tables, since an underestimated build side is a statistics problem wearing a memory problem's clothing.
5. Capture the plan under the guarded runbook to read the actual Batches and Memory Usage figures, and to test a higher work_mem safely in a single session.

## 6. Prerequisites

- Role membership in pg_monitor (or pg_read_all_stats).
- pg_stat_statements for the statement-level temp file attribution.
- log_temp_files enabled (a value of 0 logs every temp file) is extremely helpful for attributing spills to statements over time; on Aurora the log is exported to CloudWatch Logs.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_statements_writing_temp_files.sql`](scripts/01_statements_writing_temp_files.sql) -- Ranks statements by temporary block volume, the statement-level signature of a spilling hash join.
2. [`scripts/02_cluster_temp_file_trend.sql`](scripts/02_cluster_temp_file_trend.sql) -- Measures cluster-wide temporary file volume to judge whether spilling is systemic or isolated.
3. [`scripts/03_memory_and_spill_settings.sql`](scripts/03_memory_and_spill_settings.sql) -- Reviews the memory settings that determine whether a hash join stays in memory or spills.
4. [`scripts/04_statistics_freshness_on_join_inputs.sql`](scripts/04_statistics_freshness_on_join_inputs.sql) -- Checks whether the planner's size estimates for the joined tables are current.
5. [`scripts/05_test_memory_hypothesis_safely.md`](scripts/05_test_memory_hypothesis_safely.md) -- Guarded runbook for confirming a hash spill in the plan and testing a larger work_mem without endangering the instance.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Temporary files are written to the instance's local storage, not to the shared Aurora cluster volume. Their capacity is therefore a property of the instance class, and exhausting it produces query failures rather than cluster-level storage growth.
- work_mem is set through the Aurora DB cluster or DB instance parameter group; ALTER SYSTEM is not available. A per-role default (ALTER ROLE ... SET work_mem) is the usual way to give a reporting role more memory than the order-path role, and it requires no reboot.
- Running the analytical workload on a dedicated reader with its own DB instance parameter group is the cleanest Aurora-native separation: the reader can carry a large work_mem without exposing the writer to the same risk.

## 8. Interpretation Guide

- Batches greater than 1 on a Hash node in an EXPLAIN ANALYZE plan is the definitive confirmation of a spill. Batches reported as 'N (originally M)' means the planner expected M and had to grow to N at run time, which is simultaneously a spill and proof of an underestimate.
- work_mem is a per-node, per-worker limit rather than a per-query or per-connection one: one query with two hash joins running across four parallel workers can use many multiples of it at once. That is why raising it globally on a high-connection exchange writer is risky.
- hash_mem_multiplier scales the memory available to hash operations specifically. Raising it preferentially helps hash joins and hash aggregates without giving every sort the same increase, which is usually what a reporting-heavy workload actually wants.
- If the build side estimate is accurate and the input is genuinely huge, more memory is the wrong answer: reduce the input instead through better predicates, partition pruning, or pre-aggregation.
- temp_blks_written in pg_stat_statements is cumulative per statement and does not distinguish a hash spill from a sort spill or a large materialize -- it identifies candidates, and only the plan identifies the node.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- For a one-off report that must complete now, raise work_mem for that session alone with SET before running it, rather than changing cluster configuration under time pressure.
- If the instance is close to exhausting local storage because of concurrent spills, stop or defer the non-critical spilling workloads first.

**Short-term remediation** (hours to days):

- Run a targeted ANALYZE on the build-side table if its statistics are stale, which often removes the spill entirely by letting the planner size the hash table correctly or pick the smaller input to build from.
- Raise work_mem or hash_mem_multiplier for the specific role that runs the reporting workload, rather than for every connection on the cluster.
- Add the predicate or index that reduces the build side to the rows the report actually needs.

**Long-term engineering fix** (days to weeks):

- Separate the analytical workload onto dedicated Aurora readers with their own parameter group, so reporting-sized work_mem does not have to be granted to the order-path writer.
- Pre-aggregate the recurring reconciliation and settlement joins into summary tables refreshed on a schedule, so the large hash join happens once rather than on every report execution.
- Partition the large fact tables (trades, ledger_entries) by time so reports naturally touch a bounded subset.

## 10. Production Safety

- All .sql scripts here are read-only and safe during trading hours.
- Testing a larger work_mem is a guarded runbook step, not a script: work_mem multiplies across nodes, workers, and connections, so an unconsidered increase is one of the fastest ways to drive an instance into memory exhaustion. Deciding to actually execute a candidate production query is an operator judgement call, not something an investigation script may do on the operator's behalf. That is why every EXPLAIN ANALYZE step in this toolkit is a markdown runbook rather than a .sql file.
- Never raise work_mem cluster-wide as a first response. Session-scoped and role-scoped changes deliver the same benefit to the affected workload with a fraction of the risk.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Local instance storage is close to exhaustion because of concurrent temporary file usage -- escalate immediately, as this fails queries outright rather than merely slowing them.
- A reporting query with a compliance or settlement deadline cannot be made to complete within its window even with a reasonable memory allocation.
- The join is genuinely too large for any sane work_mem, meaning the data model or the report definition has to change -- escalate to engineering rather than continuing to tune.

## 12. Related Issues

- [sort-spills](../sort-spills/README.md)
- [temp-file-investigation](../temp-file-investigation/README.md)
- [analyze-query-plan](../analyze-query-plan/README.md)
- [merge-join-analysis](../merge-join-analysis/README.md)
- [cardinality-estimation](../cardinality-estimation/README.md)
- [high-iops](../../performance/high-iops/README.md)
