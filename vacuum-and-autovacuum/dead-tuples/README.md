# Dead Tuple Accumulation

**Category:** Vacuum and Autovacuum | **Workflow:** `vacuum-and-autovacuum/dead-tuples`

## 1. Problem Description

Investigates elevated dead tuple counts/ratios across tables -- the direct precursor to bloat, degraded index efficiency, and increased I/O, and the primary metric autovacuum acts on.

## 2. Typical Symptoms

- Rising n_dead_tup on one or more tables.
- Growing gap between n_live_tup + n_dead_tup and the table's expected logical row count.

## 3. Business Impact

- Dead tuples directly inflate table and index size, increasing I/O for every scan and reducing effective cache hit ratio for hot tables.

## 4. Possible Root Causes

- High UPDATE/DELETE churn on a table (common for order status transitions, balance updates) outpacing vacuum's cleanup rate.
- A long-running transaction preventing cleanup of tuples that are otherwise eligible.
- autovacuum thresholds (scale_factor) too high in absolute terms for a very large table.

## 5. Investigation Strategy

1. Rank tables by dead tuple count/ratio.
2. Cross-reference with UPDATE/DELETE volume (n_tup_upd, n_tup_del) to confirm churn is the driver.
3. Check for a blocking transaction preventing cleanup.

## 6. Prerequisites

- pg_monitor role membership.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_dead_tuples_ranked.sql`](scripts/01_dead_tuples_ranked.sql) -- Ranks tables by dead tuple count and ratio.

## 8. Interpretation Guide

- A table with high n_tup_upd/n_tup_del and correspondingly high n_dead_tup is behaving as expected for a busy OLTP table -- the question is whether autovacuum's scale_factor threshold is appropriate for its absolute size, not whether dead tuples exist at all (some level is normal and expected between vacuum cycles).

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Manually VACUUM tables with a critically high dead_tuple_pct if autovacuum has not yet caught up.

**Short-term remediation** (hours to days):

- Lower autovacuum_vacuum_scale_factor for large, high-churn tables (default 20% of table size is very large in absolute terms for a multi-million-row table).

**Long-term engineering fix** (days to weeks):

- See vacuum-and-autovacuum/autovacuum-not-keeping-up for systemic tuning; see partitioning/ for tables where per-partition vacuum would help.

## 10. Production Safety

- Investigation scripts are read-only; manual VACUUM guidance is non-blocking.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Dead tuple ratio remains high and growing despite tuning -- escalate to autovacuum-not-keeping-up for a deeper investigation.

## 12. Related Issues

- [autovacuum-not-keeping-up](../autovacuum-not-keeping-up/README.md)
- [table-bloat](../table-bloat/README.md)
