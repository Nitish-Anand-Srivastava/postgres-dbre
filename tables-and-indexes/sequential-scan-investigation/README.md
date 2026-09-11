# Sequential Scan Investigation

**Category:** Table and Index Health | **Workflow:** `tables-and-indexes/sequential-scan-investigation`

## 1. Problem Description

Deep-dive investigation into why a specific table or query is using a sequential scan instead of an expected index scan.

## 2. Typical Symptoms

- A specific query's EXPLAIN plan shows Seq Scan on a large table where an Index Scan was expected.

## 3. Business Impact

- An unexpected sequential scan on a large hot table is a direct, often severe, latency and CPU/IO cost.

## 4. Possible Root Causes

- No index exists for the query's predicate.
- An index exists but the planner chose not to use it (poor selectivity estimate from stale statistics, or the predicate uses a function/cast the index cannot support).
- The table is small enough that the planner correctly judges a sequential scan cheaper (not actually a problem).

## 5. Investigation Strategy

1. Confirm table size -- a seq scan on a genuinely small table is expected and fine.
2. Check for an existing, usable index matching the query's predicate.
3. Check statistics freshness, since stale stats can cause the planner to misjudge selectivity and skip a usable index.
4. Obtain EXPLAIN to see the planner's actual reasoning/estimates.

## 6. Prerequisites

- Query text/plan for the specific case under investigation.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_sequential_scan_heavy_tables.sql`](scripts/01_sequential_scan_heavy_tables.sql) -- Confirms which tables are experiencing the most sequential-scan read volume.
2. [`scripts/02_statistics_freshness.sql`](scripts/02_statistics_freshness.sql) -- Checks whether stale statistics could be causing the planner to misjudge selectivity and avoid an existing index.

## 8. Interpretation Guide

- A sequential scan on a table under a few thousand rows (or a few MB) is frequently the CORRECT and fastest plan -- do not chase 'seq_scan > 0' as inherently bad; focus on large tables where the ratio of rows read to rows returned is poor.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- None -- diagnose before acting.

**Short-term remediation** (hours to days):

- Add a targeted index if none exists and the table/row-selectivity justifies one; refresh statistics if staleness is the cause.

**Long-term engineering fix** (days to weeks):

- See missing-index-candidates for the broader, table-wide review.

## 10. Production Safety

- Investigation is read-only; EXPLAIN (without ANALYZE) never executes the query.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- The planner ignores an existing, seemingly-appropriate index even with fresh statistics -- escalate to query-optimization/analyze-query-plan for a deeper plan-level investigation.

## 12. Related Issues

- [missing-index-candidates](../missing-index-candidates/README.md)
- [analyze-query-plan](../../query-optimization/analyze-query-plan/README.md)
