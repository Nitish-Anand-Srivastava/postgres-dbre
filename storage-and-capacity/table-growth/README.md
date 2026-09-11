# Table Growth Investigation

**Category:** Storage and Capacity | **Workflow:** `storage-and-capacity/table-growth`

## 1. Problem Description

One or more specific tables are growing faster than expected and you need to establish whether that growth is real inserted data, update churn leaving dead tuples behind, TOAST expansion from wide payload columns, or index overhead. These four causes look identical from a size graph and have completely different fixes, so this workflow measures write volume alongside size instead of reasoning from size alone. The canonical exchange offenders are the trade tape and order table (pure insert volume), the wallet and balance tables (update churn on a small row set), and audit or order-book snapshot tables (wide TOASTed payloads written once and never read again).

## 2. Typical Symptoms

- A specific table appears at the top of the largest-relations list and its position is climbing week over week.
- Queries against the table have become progressively slower even though their plans have not changed and the index set is the same.
- Autovacuum runs on this table take dramatically longer than they did last quarter, or never seem to finish before the next one is triggered.
- The table's index set is now larger than the table's own heap.
- `n_dead_tup` on the table is persistently high and does not fall after an autovacuum cycle completes.

## 3. Business Impact

- Growth concentrated in the order or trade tables directly degrades the hot path of the exchange -- order placement, matching, and fill lookups.
- Growth in the ledger increases settlement and reconciliation batch duration, squeezing the overnight window that regulatory reporting depends on.
- Every additional index byte on a write-heavy table multiplies write amplification: the same insert now dirties more pages, generates more WAL, and takes longer to vacuum.
- Unbounded growth eventually forces an emergency, high-risk intervention (partitioning or archival under time pressure) on a business-critical table, which is far riskier than doing the same work on a schedule.

## 4. Possible Root Causes

- Insert volume: genuine, expected append-only growth (trade tape, ledger entries, deposit/withdrawal history) with no retention policy.
- Update churn: hot rows updated repeatedly (wallet balances, order status transitions) where each non-HOT update writes a new row version plus a new entry in every index.
- Update churn: HOT updates prevented by an index on a frequently-updated column, turning cheap in-page updates into full row-plus-index rewrites.
- Bloat: dead tuples accumulating because autovacuum is throttled, starved of workers, or repeatedly cancelled by conflicting locks.
- Bloat: the xmin horizon held back by a long-running transaction, an idle-in-transaction session, or an inactive replication slot, so vacuum cannot remove tuples it otherwise would.
- TOAST: wide JSON/JSONB or bytea columns (raw venue responses, signed transaction payloads) pushing large values out of line and growing the TOAST relation faster than the heap.
- Indexes: indexes added incrementally over time to fix individual slow queries, never reviewed as a set.
- Schema: soft deletes (`deleted_at IS NOT NULL`) or status-flag patterns that keep historical rows in the hot table forever.

## 5. Investigation Strategy

1. Rank tables by total size to confirm exactly which relations are in scope, and record the numbers so the next run can be compared against them.
2. Split each in-scope relation into heap, TOAST, and index components -- this single step eliminates two of the four possible causes immediately.
3. Measure write volume per table (inserts, updates, deletes, HOT update ratio) to distinguish append-only growth from update churn.
4. Check dead tuple accumulation to establish whether a meaningful fraction of the size is reclaimable space rather than live data.
5. Compare measured growth against the size history collector, if deployed, to get a real rate rather than a snapshot.
6. Drill into the single worst table for its exact size, row estimates, and vacuum/analyze timestamps before deciding on remediation.

## 6. Prerequisites

- `pg_monitor` role membership (or `pg_read_all_stats`) and `CONNECT` on the target database.
- Awareness of when statistics were last reset (`pg_stat_database.stats_reset`) -- every write counter here is cumulative since that moment, and a recent failover resets them.
- Ideally the `dba_toolkit.table_size_history` collector deployed, so growth can be measured rather than inferred.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_largest_tables.sql`](scripts/01_largest_tables.sql) -- Establishes which relations are actually in scope, ranked by total size, before any deeper analysis.
2. [`scripts/02_table_size_components.sql`](scripts/02_table_size_components.sql) -- Splits the in-scope relations into heap, TOAST, and index bytes to narrow four possible growth causes down to one or two.
3. [`scripts/03_write_volume_by_table.sql`](scripts/03_write_volume_by_table.sql) -- Measures inserts, updates, deletes, and the HOT update ratio per table to distinguish append-only growth from update churn.
4. [`scripts/04_dead_tuples_ranked.sql`](scripts/04_dead_tuples_ranked.sql) -- Quantifies how much of each table's footprint is dead tuples awaiting reclamation rather than live data.
5. [`scripts/05_measured_growth_from_history.sql`](scripts/05_measured_growth_from_history.sql) -- Reports actual measured growth per table over the retention window, using the size-history collector rather than a single snapshot.
6. [`scripts/06_single_table_deep_dive.sql`](scripts/06_single_table_deep_dive.sql) -- Drills into one named table for exact size, live/dead row estimates, and vacuum/analyze recency before committing to a remediation path.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Deleting rows from a large table on Aurora frees space for reuse inside the relation but returns nothing to the Aurora volume, and the delete itself generates WAL and dead tuples. Partition detach avoids both problems and is strongly preferred at exchange data volumes.
- Autovacuum cost parameters are set through the Aurora cluster parameter group, not `postgresql.conf`; per-table `ALTER TABLE ... SET (autovacuum_*)` overrides still work normally and are the right tool for one oversized relation.
- `pg_stat_all_tables` counters reset on instance restart and on failover. After an Aurora failover the new writer starts from zero, so a sudden 'drop' in write volume immediately after a failover event is an artifact, not a workload change.

## 8. Interpretation Guide

- High `n_tup_ins` with near-zero `n_tup_upd` and `n_tup_del` is clean append-only growth. There is no bloat to reclaim and no vacuum tuning that will help -- the only levers are partitioning, retention, and archival.
- High `n_tup_upd` with a low `pct_hot_updates` is the most expensive pattern in PostgreSQL: every update writes a new row version *and* a new entry in every index on the table. Look for an index on the column being updated (a `status` or `updated_at` column is the usual culprit) and consider whether it can be dropped or the fillfactor lowered to allow HOT updates.
- `n_dead_tup` above roughly 20% of `n_live_tup` that persists across autovacuum cycles means space is being consumed by tuples that *should* be reclaimable -- this is a vacuum problem, not a growth problem, and belongs in the vacuum category.
- A TOAST share above roughly 40% means the table is really a document store wearing a relational table's clothes. Evaluate whether the payload is ever queried, or only ever written and occasionally fetched by primary key -- in the latter case object storage is usually the right home.
- `estimated_row_count` from `reltuples` is only as fresh as the last vacuum or analyze; if `last_analyze` and `last_autoanalyze` are both old, treat the row estimate as unreliable and do not use it for projections.
- If growth is real, sustained, and in a table that cannot be deleted from for regulatory reasons, stop investigating and start designing: this is a partitioning-plus-archival project, and the only question left is timing.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- None required -- table growth is a trend. Do not run `VACUUM FULL` on a large production table as a reflex; it takes an `AccessExclusiveLock` for its entire duration and will stall the trading path.
- If growth turns out to be dead tuples rather than live data, clearing whatever is holding back the xmin horizon (an idle-in-transaction session, an abandoned replication slot) is genuinely immediate and low-risk.

**Short-term remediation** (hours to days):

- Drop confirmed-unused and duplicate indexes on the table to cut both stored bytes and per-write amplification.
- Lower `fillfactor` on an update-heavy table (via a schema-changes DDL runbook) so future updates can take the HOT path and avoid touching every index.
- Tune autovacuum per-table (`autovacuum_vacuum_scale_factor`, cost limits) so a large table is vacuumed on a sensible cadence rather than the cluster default, which scales badly at size.
- Introduce a conservative retention window on the table's oldest data, even before a full partitioning project, to arrest the trend.

**Long-term engineering fix** (days to weeks):

- Partition the table on its natural time or tenant key so retention becomes a metadata-only `DETACH PARTITION` instead of a `DELETE` that generates bloat and WAL.
- Split wide payload columns into a separate relation, or move them to object storage with only a reference and indexed metadata retained in PostgreSQL.
- Replace soft-delete and status-history-in-place patterns with an explicit history table (or an event log) that has its own independent retention.
- Add growth budgets and retention policies to the schema review checklist so this table is the last one that reaches this state unmanaged.

## 10. Production Safety

- Every script here is read-only. The write-volume and dead-tuple scripts read cumulative statistics views and are safe under any load.
- The single-table deep-dive script ships with an illustrative default table name guarded by `to_regclass()`, so it prints guidance rather than failing if that table does not exist in your database.
- Do not use `count(*)` on a multi-hundred-GB table to 'check the real row count' during a busy period -- it is a full heap scan. The `reltuples` estimate plus `last_analyze` is sufficient for capacity work.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- The fastest-growing table is the financial ledger or another relation under a regulatory retention mandate -- archival design needs compliance sign-off before any DBA action.
- Growth rate has more than doubled with no corresponding change in trading volume or deployment -- treat it as unexpected-storage-growth rather than normal capacity planning.
- Remediation requires partitioning a table that is on the live order-placement path -- that migration needs database engineering leadership and a formal change window.
- Dead tuples remain high across multiple autovacuum cycles despite no long-running transactions and no lagging replication slots -- escalate to the vacuum category and, if unexplained, to AWS support.

## 12. Related Issues

- [database-growth](../database-growth/README.md)
- [index-growth](../index-growth/README.md)
- [capacity-forecasting](../capacity-forecasting/README.md)
- [rapidly-growing-tables](../../tables-and-indexes/rapidly-growing-tables/README.md)
- [table-bloat](../../vacuum-and-autovacuum/table-bloat/README.md)
- [investigate-partitioning-candidate](../../partitioning/investigate-partitioning-candidate/README.md)
- [investigate-archiving-candidate](../../archival-and-data-lifecycle/investigate-archiving-candidate/README.md)
