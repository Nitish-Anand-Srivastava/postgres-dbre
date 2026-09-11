# 06_plan_baseline_comparison

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `06_plan_baseline_comparison.md` |
| Purpose | Guarded runbook for comparing the current plan against a stored baseline, and for creating baselines when none exist. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Reader instance preferred for read-only statements. |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | Step 1 and baseline capture: none, EXPLAIN does not execute the statement. Step 2: a full execution of the statement, bounded by statement_timeout. |
| Required privileges | The same privileges the statement under investigation requires. |
| Prerequisites | Scripts 01-05 completed, the regressed statement identified with representative parameters, and the stored baseline retrieved if one exists. |
| Execution order | Step 06 of workflow `query-optimization/query-plan-regression` |
| Related scripts | ../analyze-query-plan/README.md, ../../database-health/pre-deployment-check/README.md |

## How to interpret / use this runbook

The plan-shape diff from step 1 is the deliverable and costs nothing to obtain; execute the statement only when you need actual row counts to explain the shape change. If no baseline exists, treat creating one for the exchange's critical statements as the primary output of this investigation -- it is what converts the next regression from an archaeology exercise into a comparison.

---

## If you have a baseline

### Step 1 -- Capture the current plan, for free

```sql
EXPLAIN (COSTS OFF, FORMAT TEXT)
SELECT ... ;                      -- the regressed statement, real parameters
```

`COSTS OFF` strips the cost numbers and leaves the plan **shape**, which is what you
want for a diff: shapes are stable across data growth, costs are not. Nothing is
executed.

Diff it against the stored baseline. The differences to look for, in order of how
often they explain a regression:

1. A join strategy changed (`Hash Join` became `Nested Loop`, or the reverse).
2. An access path changed (`Index Scan` became `Seq Scan`).
3. The join order changed.
4. A `Sort` or `Materialize` node appeared where there was none.
5. Parallelism appeared or disappeared (`Gather` nodes).

### Step 2 -- Only if the shape diff is not conclusive

```sql
SET LOCAL statement_timeout = '20s';
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT ... ;
```

This executes the statement. Use it when you need estimated-versus-actual row
counts to explain *why* the shape changed, not merely to observe *that* it changed.
Prefer a reader; wrap any write statement in `BEGIN ... ROLLBACK`.

## If you do not have a baseline

You cannot prove a regression from the database alone -- pg_stat_statements gives
you aggregates, not history, and an Aurora failover may have reset even those. Do
two things:

1. Use the application's own latency metrics as the before picture, and this
   workflow's scripts 03, 04, and 05 to identify what changed around that moment.
2. **Create the baseline now**, so the next occurrence is a two-minute comparison.

## Creating plan baselines

For each of the exchange's critical statements -- order placement, order
cancellation, balance lookup, trade history, withdrawal processing, settlement
batch -- capture and store:

```sql
EXPLAIN (COSTS OFF, FORMAT TEXT)
SELECT ... ;
```

Store alongside it: the `queryid` from pg_stat_statements, the exact parameter
values used, the instance and cluster the capture came from, the timestamp, the
engine version, and the current `mean_exec_time` and `calls`. Keep it in version
control next to the application code that issues the statement, so the baseline is
reviewed whenever the query is changed.

Capture baselines at three moments: as part of
`database-health/pre-deployment-check`, after any significant data growth
milestone, and after any deliberate planner parameter change.

## Applying the remediation

| Diff finding | Likely cause | Remediation |
|---|---|---|
| `Index Scan` became `Seq Scan` | Index invalid or dropped, or statistics changed | Rebuild the index `CONCURRENTLY`, or targeted `ANALYZE` |
| `Hash Join` became `Nested Loop` | Outer-side estimate collapsed | Targeted `ANALYZE`, then extended statistics if it persists |
| New `Sort` node appeared | Ordering index dropped or no longer chosen | Restore or extend the index |
| Shape identical, timings worse | Not a plan regression | Cold cache after failover, bloat, or resource contention -- see `performance/` |
| Fast for some parameters, slow for others | Generic plan for a prepared statement | Confirm with a capture, then consider `plan_cache_mode = force_custom_plan` at the narrowest scope |

## Never do this

- Do not set `enable_nestloop = off` (or any other plan-type switch) in the Aurora
  parameter group to force the old plan back. It is diagnostic only.
- Do not leave statistics deliberately stale because the old plan was better with
  stale statistics. Fix the estimate instead.
- Do not conclude a plan regression from timings alone after a failover: check
  instance uptime first, because a cold cache looks identical from the outside.
