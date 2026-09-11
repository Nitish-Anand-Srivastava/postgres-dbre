# Investigating a Partitioning Candidate

**Category:** Partitioning | **Workflow:** `partitioning/investigate-partitioning-candidate`

## 1. Problem Description

Determines whether a given table is actually a good candidate for partitioning before committing to the significant engineering effort of partition-existing-large-table.

## 2. Typical Symptoms

- A table has grown large enough that vacuum, backup, or query performance concerns are being raised.
- A table has an obvious time-based or range-based access pattern (append-mostly, queries scoped to recent data).

## 3. Business Impact

- Partitioning is a significant, higher-risk migration -- investing the effort without confirming a genuine access-pattern fit wastes engineering time and introduces unnecessary risk.

## 4. Possible Root Causes

- N/A -- this is a feasibility assessment workflow, not an incident investigation.

## 5. Investigation Strategy

1. Check table size and growth trend.
2. Check whether queries are naturally scoped by a candidate partition key (date range, tenant id, status) via pg_stat_statements query text review.
3. Check current constraint/index/FK complexity, since that determines migration difficulty.
4. Check whether the access pattern favors range, list, or hash partitioning.

## 6. Prerequisites

- pg_stat_statements for query-pattern review.
- pg_monitor role membership.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_table_size_and_growth.sql`](scripts/01_table_size_and_growth.sql) -- Checks current size and row count for the candidate table as the baseline feasibility input.
2. [`scripts/02_query_pattern_review.sql`](scripts/02_query_pattern_review.sql) -- Surfaces the top statements touching the candidate table to assess whether a dominant filter column (candidate partition key) exists.
3. [`scripts/03_constraint_and_fk_complexity.sql`](scripts/03_constraint_and_fk_complexity.sql) -- Inventories existing constraints and foreign keys referencing/referenced-by the candidate table, since these materially affect migration difficulty.

## 8. Interpretation Guide

- The best partitioning candidates are large (multi-GB+), append-heavy or time-series-like, and queried predominantly with a predicate on the candidate partition key (enabling partition pruning). A table queried broadly across its entire range with no dominant filter column is a poor hash/range candidate and may not benefit.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- N/A.

**Short-term remediation** (hours to days):

- If a good candidate is confirmed, proceed to partition-existing-large-table for the full migration runbook.

**Long-term engineering fix** (days to weeks):

- Build partition-key awareness into new large-table schema design from the outset (see the root README's crypto-exchange ledger-table-growth guidance) to avoid this retrofit exercise in the future.

## 10. Production Safety

- All scripts here are read-only.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- A confirmed candidate is business-critical (financial ledger) -- involve database engineering leadership before committing to the migration plan.

## 12. Related Issues

- [partition-existing-large-table](../partition-existing-large-table/README.md)
- [table-growth](../../storage-and-capacity/table-growth/README.md)
