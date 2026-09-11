# 04_statistics_maintenance_runbook

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `04_statistics_maintenance_runbook.md` |
| Purpose | Guarded runbook for applying the statistics maintenance actions this workflow identifies: targeted ANALYZE, per-table thresholds, statistics targets, and extended statistics. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only (the query reads/writes state that only exists or is meaningful on the writer) |
| Safety | LOW RISK WRITE (ANALYZE and statistics DDL; SHARE UPDATE EXCLUSIVE locks with a brief ACCESS EXCLUSIVE for column-level DDL, no table rewrite -- see per-step notes) |
| Expected impact | Real I/O for the duration of each ANALYZE on a large table; brief lock acquisition for the DDL steps, which can queue behind a long-running transaction if lock_timeout is not set. |
| Required privileges | Table owner, or a role granted the `MAINTAIN` privilege on the table (PostgreSQL 16+), or a role with `pg_maintain` membership. DDL variants additionally require the privileges needed for the specific DDL statement (e.g. ownership to ALTER TABLE). |
| Prerequisites | Full read-only investigation for this workflow completed; maintenance window and second engineer approval obtained. |
| Execution order | Step 04 of workflow `maintenance/statistics-maintenance` |
| Related scripts | 01_statistics_drift_ranking.sql, 03_column_targets_and_extended_statistics.sql, ../routine-maintenance-checklist/README.md |

## How to interpret / use this runbook

Apply one change at a time and verify its effect on a real plan before the next -- statistics tuning applied in bulk is impossible to attribute, and every raised target and extended statistics object carries an ongoing ANALYZE and planning cost.

---

Every statement in this runbook is a real database operation. Read the lock and cost notes for each step before running it, and apply one change at a time so the effect of each is measurable.

## 1. Targeted ANALYZE (start here)

```sql
ANALYZE VERBOSE public.trades;
```

Replace with the actual drifted table from script 01. `ANALYZE` takes a SHARE UPDATE EXCLUSIVE lock -- ordinary reads and writes continue, but it conflicts with VACUUM, another ANALYZE, and DDL on the same table. On a very large table this is real, sustained I/O, so run it off-peak and one table at a time.

Rollback: none needed, and none possible -- an ANALYZE only replaces statistics with more current statistics. The 'risk' of running it is the I/O it consumes, not the result.

## 2. Per-table autoanalyze thresholds for very large tables

```sql
ALTER TABLE public.trades SET (
    autovacuum_analyze_scale_factor = 0.01,
    autovacuum_analyze_threshold    = 50000
);
```

This makes autoanalyze fire after roughly 1% of the table plus 50,000 rows have changed, instead of the default 10%. `ALTER TABLE ... SET (...)` for storage parameters takes a brief SHARE UPDATE EXCLUSIVE lock -- it does not rewrite the table and completes in milliseconds -- but it will queue behind a long-running transaction holding a conflicting lock, so use a `lock_timeout` to avoid parking a lock request in front of production traffic:

```sql
SET lock_timeout = '5s';
```

Rollback: `ALTER TABLE public.trades RESET (autovacuum_analyze_scale_factor, autovacuum_analyze_threshold);` returns the table to the cluster-wide defaults.

## 3. Raise the statistics target on a specific skewed column

```sql
ALTER TABLE public.trades ALTER COLUMN market_symbol SET STATISTICS 500;
ANALYZE public.trades;
```

The new target does nothing until the following ANALYZE runs. Higher targets cost more ANALYZE time and more planning time on every query touching that column, so raise it for columns whose skew is actually producing bad estimates -- typically a market/symbol, currency, or status column where a few values dominate and a long tail is thin. This is DDL on the table and takes an ACCESS EXCLUSIVE lock briefly; keep `lock_timeout` set.

Rollback: `ALTER TABLE public.trades ALTER COLUMN market_symbol SET STATISTICS DEFAULT;` restores the cluster-wide default_statistics_target (PostgreSQL 17 accepts the older `SET STATISTICS -1` spelling for the same effect).

## 4. Extended statistics for correlated columns

```sql
CREATE STATISTICS trades_symbol_side_stats (ndistinct, dependencies, mcv)
    ON market_symbol, side
    FROM public.trades;
ANALYZE public.trades;
```

Use this where the planner underestimates a predicate on two columns that are not independent in practice (symbol and side, currency and account type, status and created-date range). `CREATE STATISTICS` takes a SHARE UPDATE EXCLUSIVE lock and the object stays empty until the next ANALYZE populates it -- verify with script 03 that the populated flags flipped to true.

Rollback: `DROP STATISTICS trades_symbol_side_stats;`

## 5. Make post-load ANALYZE part of the job, not an afterthought

Any batch load, backfill, or large archival delete should end with an ANALYZE of the affected table inside the same job. This is the single highest-value change in this runbook, because it removes the window in which plans are chosen from a distribution that no longer exists.

## Verify

Re-run scripts 01 and 03 after each change, and confirm the specific query whose plan motivated the change now estimates rows sensibly (compare the estimate against actual rows using `query-optimization`'s plan-analysis workflows). A statistics change that does not move a real plan estimate was not worth its ongoing ANALYZE cost.
