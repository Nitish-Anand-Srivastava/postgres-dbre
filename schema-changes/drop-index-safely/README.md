# Dropping an Index Safely

**Category:** Schema Changes and DDL | **Workflow:** `schema-changes/drop-index-safely`

## 1. Problem Description

An index looks unused and someone wants to remove it. Dropping an index is trivially easy and disproportionately dangerous: the statement takes a second, and if the index turns out to have been serving a query that only runs at month-end reconciliation, the consequence is a full sequential scan of a multi-hundred-gigabyte table discovered under time pressure during the regulatory reporting window. This workflow is therefore built around evidence and reversibility rather than around the statement itself. It establishes that the index is genuinely unused across every instance and a full business cycle, confirms it is not structurally required, rehearses the drop inside a transaction that is then rolled back, and only then removes it -- concurrently, so the removal itself blocks nothing.

## 2. Typical Symptoms

- An index review has identified indexes with zero scans since the last statistics reset.
- Structurally duplicate indexes exist on the same table under different names.
- Index storage on a write-heavy table has grown to exceed the table's own heap size.
- Write latency on the trading path has degraded as indexes accumulated over time.
- An INVALID index from a failed build is consuming storage while providing nothing.

## 3. Business Impact

- Removing genuinely unused indexes reduces write amplification on the hottest path in the exchange, cuts WAL volume and reader lag, and shortens every vacuum cycle -- it is one of the highest-value, lowest-effort optimizations available.
- Removing an index that was actually needed causes an immediate, severe query regression, typically discovered when a periodic job runs and takes hours instead of minutes.
- Rebuilding a mistakenly dropped index on a large table takes hours and cannot be done quickly under pressure, so the recovery from a wrong drop is slow.
- On Aurora, dropping an index frees space for reuse but does not reduce billed storage, so the benefit is in write performance rather than cost.

## 4. Possible Root Causes

- N/A -- this is a planned change workflow. Candidates come from the index-growth and unused-indexes investigations.

## 5. Investigation Strategy

1. Identify never-scanned candidates, deliberately excluding indexes that back constraints.
2. Identify structural duplicates, which are the safest possible candidates because the surviving copy serves exactly the same queries.
3. For each candidate, establish its structural role: primary key, unique constraint, replica identity, foreign-key support, or purely a query optimization.
4. Confirm the usage evidence spans a full business cycle and every instance in the cluster, not just the writer since the last failover.
5. Rehearse the drop inside a transaction and roll it back, using `EXPLAIN` to prove the affected queries do not regress.
6. Drop concurrently, then monitor query performance for a regression over the following days.

## 6. Prerequisites

- Index or table ownership for the drop; `pg_monitor` for the investigation.
- Usage statistics accumulated across at least one full business cycle, including month-end and quarter-end reconciliation and regulatory reporting.
- Usage statistics from every instance in the cluster, since reporting traffic is often pinned to a reader.
- Sign-off from the team owning the queries against the table.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_unused_index_candidates.sql`](scripts/01_unused_index_candidates.sql) -- Lists never-scanned, non-constraint-backing indexes as candidates, with the caveats that make a candidate list not a decision.
2. [`scripts/02_duplicate_index_candidates.sql`](scripts/02_duplicate_index_candidates.sql) -- Finds structurally identical indexes, which are the safest possible drop candidates.
3. [`scripts/03_index_role_and_drop_verdict.sql`](scripts/03_index_role_and_drop_verdict.sql) -- Establishes the structural role of every index on the target table and produces an explicit per-index verdict.
4. [`scripts/04_drop_index_safely_runbook.md`](scripts/04_drop_index_safely_runbook.md) -- The guarded DDL runbook for dropping an index, including the transaction-rollback rehearsal that proves the drop is safe first.
5. [`scripts/05_post_drop_regression_check.sql`](scripts/05_post_drop_regression_check.sql) -- Watches for a query regression after the drop, over a window long enough to include periodic jobs.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- `idx_scan` and `last_idx_scan` reset on instance restart and on every Aurora failover. After a failover, every index on the new writer reads as unused -- wait for a full business cycle of fresh statistics before making any drop decision.
- Index usage counters are per instance. Check every reader as well as the writer, because reporting traffic pinned to a reader produces exactly the pattern that makes a needed index look droppable.
- Dropping an index frees its space for reuse inside the Aurora volume but does not reduce the billed high-water mark. The benefit is reduced write amplification, WAL volume, and vacuum time -- not storage cost.
- Reduced WAL volume from fewer indexes directly reduces Aurora reader lag on a write-heavy table, which is often the most valuable outcome of an index cleanup.

## 8. Interpretation Guide

- `idx_scan = 0` is necessary but nowhere near sufficient. The counter resets on instance restart and on every Aurora failover, so a zero on the writer may mean 'nothing used this since the failover an hour ago' rather than 'nothing has ever used this'.
- `last_idx_scan` (PostgreSQL 16+) is far more trustworthy, because a timestamp survives as evidence in a way a counter does not. An index last scanned eight months ago is genuinely unused.
- Check usage on the readers, not only the writer. Reporting and analytics traffic is commonly routed to a reader, and an index used exclusively by those queries reads as unused on the writer.
- Never drop an index backing a primary key, unique, or exclusion constraint by name -- drop the constraint instead, which removes the index with it. Attempting the direct drop simply fails.
- An index that is the table's replica identity must not be dropped while logical replication depends on it, or `UPDATE` and `DELETE` on that table will start failing.
- An index supporting a foreign key must not be dropped on scan counts alone. It may show zero scans while still preventing every parent delete from sequentially scanning the child table, because that check does not always register as an index scan in the same way.
- Structural duplicates are the highest-confidence candidates in the whole workflow: by definition the surviving copy serves exactly the same queries, so the planner cannot regress. Keep the one with the clearer name and the longer usage history.
- A `DROP INDEX` inside an explicit transaction is fully reversible by `ROLLBACK`, which makes a rehearsal genuinely safe -- this is the single most useful technique in this workflow and it is underused.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If a query has regressed after a drop, recreate the index concurrently immediately. Keep the exact original definition recorded before the drop so this can be done without reconstruction.

**Short-term remediation** (hours to days):

- Drop confirmed structural duplicates first -- they are risk-free and deliver immediate write-path benefit.
- Drop confirmed INVALID indexes unconditionally; the planner never used them.
- Drop never-scanned indexes one at a time with a monitoring gap between each, so any regression can be attributed to a specific drop.

**Long-term engineering fix** (days to weeks):

- Schedule a recurring index audit so accretion is corrected continuously rather than as an occasional large cleanup.
- Record the full definition of every dropped index in the change ticket, so recreating it is a copy-paste rather than a reconstruction under pressure.
- Require every new index to name the query it serves, so future audits have something to check against.

## 10. Production Safety

- All `.sql` scripts here are read-only. The drop lives in the `.md` runbook.
- Always use `DROP INDEX CONCURRENTLY` on a production table -- the plain form takes an `AccessExclusiveLock` and blocks reads as well as writes.
- `DROP INDEX CONCURRENTLY` cannot run inside a transaction block and can name only one index per statement.
- Rehearse first: `BEGIN; DROP INDEX ...; EXPLAIN <query>; ROLLBACK;` proves the planner's behavior without the index while changing nothing permanently. Note this rehearsal uses the plain form and therefore takes a strong lock for the duration of the transaction, so keep it very short and set a lock timeout.
- Record the exact index definition before dropping it. Reconstructing a definition from memory during a regression is how a bad afternoon becomes a bad week.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- The candidate is on the live order-matching or wallet-balance path -- the owning team must sign off, because a wrong drop there is an immediate trading incident.
- The index cannot be attributed to any query or team after investigation -- do not guess; escalate for ownership rather than dropping something nobody understands.
- The index is the table's replica identity or supports an active logical replication or DMS pipeline.
- A query regression is observed after a drop and recreating the index does not resolve it -- escalate, because something else changed at the same time.

## 12. Related Issues

- [failed-index-build](../failed-index-build/README.md)
- [safe-index-creation](../safe-index-creation/README.md)
- [add-index-large-table](../add-index-large-table/README.md)
- [large-table-ddl](../large-table-ddl/README.md)
- [unused-indexes](../../tables-and-indexes/unused-indexes/README.md)
- [duplicate-indexes](../../tables-and-indexes/duplicate-indexes/README.md)
- [index-growth](../../storage-and-capacity/index-growth/README.md)
- [query-plan-regression](../../query-optimization/query-plan-regression/README.md)
