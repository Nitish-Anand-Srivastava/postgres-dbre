# Storage Capacity Forecasting

**Category:** Storage and Capacity | **Workflow:** `storage-and-capacity/capacity-forecasting`

## 1. Problem Description

Turns observed growth into a defensible projection: how large will this database be in ninety or a hundred and eighty days, when does it cross the thresholds we care about, and how much runway do we have before remediation stops being optional. This workflow is deliberately a simple linear projection from measured history, because a naive model whose assumptions are written down and understood is far more useful operationally than a sophisticated one nobody can sanity-check at three in the morning. Every output here is a heuristic, not a guarantee: it assumes the last observed growth rate continues unchanged, which is exactly what a crypto exchange workload does not do around market events, listings, and volatility spikes.

## 2. Typical Symptoms

- A capacity review is due and nobody can answer 'when do we run out of runway' with a number.
- Aurora storage cost is rising and finance wants a forecast rather than a current figure.
- A partitioning or archival project needs a business case, and the case rests on projected rather than current size.
- CloudWatch `VolumeBytesUsed` is trending up and leadership wants to know how far away the Aurora 128 TiB volume ceiling is.
- A new product launch or venue listing is planned and someone must estimate its storage impact before it ships.

## 3. Business Impact

- Without a forecast, storage remediation is always reactive -- done under time pressure, on a business-critical table, with the worst available risk profile.
- Aurora storage never shrinks, so every month of unmanaged growth permanently raises the cost floor; forecasting is what converts that into a budgetable, decidable number.
- Backup, restore, clone, and failover durations all scale with volume size, so a storage forecast is implicitly a recovery-time forecast for the exchange.
- Credible projections are what buy engineering time for partitioning and archival work *before* it becomes an emergency.

## 4. Possible Root Causes

- N/A -- this is a planning workflow rather than an incident investigation. The inputs it consumes come from database-growth, table-growth, index-growth, and wal-generation.

## 5. Investigation Strategy

1. Capture the current size baseline at database and relation level, so the projection has a defensible starting point.
2. Read measured growth from the size-history collector over the retention window; this is the only real rate available.
3. Project each relation forward linearly from its observed rate and compute days-to-threshold for each.
4. Where no size history exists yet, fall back to a write-rate proxy derived from insert counters and average row width, with its weaker assumptions stated explicitly.
5. Sanity-check every projection against CloudWatch `VolumeBytesUsed`, which is the figure that actually drives cost and the volume ceiling.
6. Record the assumptions, the horizon, and the review date in the forecast worksheet so the projection can be re-evaluated rather than quietly trusted forever.

## 6. Prerequisites

- `pg_monitor` role membership (or `pg_read_all_stats`).
- The `dba_toolkit.table_size_history` collector deployed with at least two, and preferably thirty or more, days of samples. Without it, only the weaker write-rate proxy is available.
- CloudWatch history for `VolumeBytesUsed` covering the same window, to reconcile logical projections against actual billed storage.
- Agreed thresholds to forecast against (a per-table size limit, a cluster volume budget, a cost ceiling) -- a projection with no threshold produces a number nobody can act on.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_database_size_baseline.sql`](scripts/01_database_size_baseline.sql) -- Records the current per-database size baseline that every projection in this workflow starts from.
2. [`scripts/02_relation_size_baseline.sql`](scripts/02_relation_size_baseline.sql) -- Records the current per-relation size baseline so projections can be made for the relations that actually matter.
3. [`scripts/03_measured_growth_from_history.sql`](scripts/03_measured_growth_from_history.sql) -- Reports measured growth per relation over the collector's retention window -- the only genuine rate input available.
4. [`scripts/04_linear_projection_and_runway.sql`](scripts/04_linear_projection_and_runway.sql) -- Projects each relation forward linearly from its measured growth rate and computes days-to-threshold runway.
5. [`scripts/05_write_rate_projection_proxy.sql`](scripts/05_write_rate_projection_proxy.sql) -- Provides a fallback growth estimate from insert counters and average row width for databases with no size history yet.
6. [`scripts/06_capacity_forecast_worksheet.md`](scripts/06_capacity_forecast_worksheet.md) -- A structured worksheet for recording the forecast, its assumptions, its thresholds, and its review date so the projection can be challenged rather than quietly trusted.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Forecast against CloudWatch `VolumeBytesUsed`, not against the sum of `pg_database_size()`. Aurora volume only ever grows, so logical projections systematically understate billed storage -- the gap widens every time data is deleted.
- The Aurora cluster volume auto-extends in 10 GiB increments up to 128 TiB. There is no manual pre-allocation and no shrink operation; the only way to reclaim a high-water mark is to build a new cluster and cut over, which is a project in its own right.
- Aurora storage is shared across the writer and every reader, so adding readers does not change the storage forecast at all -- only write volume does.
- Aurora bills storage I/O separately from stored bytes, so a complete capacity forecast has two axes: projected volume (from this workflow) and projected I/O (from the wal-generation workflow).

## 8. Interpretation Guide

- Treat every output here as a heuristic with a stated assumption -- that the recently observed growth rate continues unchanged. That assumption is routinely wrong on an exchange, where a single listing or volatility event can double write volume for a week. Use projections to prioritize and to buy lead time, never as a commitment.
- A short observation window produces a wildly unreliable rate. Under seven days of history, treat the output as directional only; thirty days or more is where the numbers become worth quoting to anyone else.
- Look at `days_until_threshold_at_current_rate` as a triage signal, not a deadline. Under ninety days means remediation must be scheduled now, because partitioning and archival projects on a large production table take months. Over a year means note it and re-review next quarter.
- Reconcile the sum of projected logical sizes against CloudWatch `VolumeBytesUsed`. Because Aurora never releases space, actual volume growth is always greater than or equal to logical growth -- if logical growth is flat while the volume keeps climbing, the projection is missing something and the unexpected-storage-growth workflow should run first.
- The write-rate proxy is deliberately cruder than the history-based projection: it assumes average row width stays constant and that inserts dominate deletes. It is useful when you have no history, and it should be replaced by the history-based number as soon as the collector has enough samples.
- A negative or zero growth rate for a relation usually means a purge or archival ran during the window, not that the table is genuinely stable. Check with the owning team before recording a table as 'not growing'.
- Forecast indexes as part of their table, not separately -- index growth generally tracks heap growth, and forecasting them independently double-counts the same underlying insert volume.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- None -- forecasting produces decisions, not actions. If a projection shows runway measured in weeks rather than months, escalate immediately rather than continuing to model it.

**Short-term remediation** (hours to days):

- Deploy the size-history collector on every production cluster if it is not already running; there is no way to reconstruct history retroactively and every day of delay is permanently lost trend data.
- Publish the projection with its assumptions, horizon, and review date so it is challenged rather than quietly trusted.
- Schedule the remediation work implied by the shortest runway item -- index cleanup, retention policy, or archival -- while there is still time to do it carefully.

**Long-term engineering fix** (days to weeks):

- Make a storage forecast a standing input to quarterly capacity and budget reviews rather than an ad-hoc exercise triggered by a bill.
- Attach a growth budget to every high-volume table at design time, so a table exceeding its budget becomes a review trigger rather than a discovery.
- Automate the forecast into a dashboard with alerting on days-to-threshold, so the number is monitored instead of periodically recomputed by hand.
- Model the storage impact of planned product changes (new venues, new instruments, longer retention requirements) before they ship, using the per-row costs measured here.

## 10. Production Safety

- Every script here is read-only and lightweight.
- The projection scripts are guarded against the size-history table being absent and print instructions rather than failing.
- All byte thresholds are cast to `numeric` before being multiplied up to GB or TB scale; multiplying a bare psql integer variable by 1024^3 overflows int4 and raises 'integer out of range', which is why the casts are not optional.
- Do not present these projections without their caveats attached. A linear projection quoted as a fact in a leadership deck is how capacity planning loses credibility the first time a market event breaks the trend.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Any projection shows the cluster approaching the Aurora 128 TiB volume limit inside the forecast horizon -- involve AWS support and engineering leadership immediately.
- Projected runway on a business-critical relation is under ninety days, which is less than a realistic partitioning or archival project takes -- this needs prioritization at leadership level, not a DBA backlog ticket.
- Projected storage cost growth exceeds the budgeted envelope -- a finance and engineering decision, not a database one.
- Actual measured growth has diverged sharply from the previous forecast with no known cause -- re-run unexpected-storage-growth before issuing a revised number.

## 12. Related Issues

- [database-growth](../database-growth/README.md)
- [table-growth](../table-growth/README.md)
- [index-growth](../index-growth/README.md)
- [unexpected-storage-growth](../unexpected-storage-growth/README.md)
- [wal-generation](../wal-generation/README.md)
- [capacity-health-check](../../database-health/capacity-health-check/README.md)
- [rapidly-growing-tables](../../tables-and-indexes/rapidly-growing-tables/README.md)
