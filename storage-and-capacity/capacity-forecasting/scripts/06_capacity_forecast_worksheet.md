# 06_capacity_forecast_worksheet

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `06_capacity_forecast_worksheet.md` |
| Purpose | A structured worksheet for recording the forecast, its assumptions, its thresholds, and its review date so the projection can be challenged rather than quietly trusted. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Any instance (writer or reader) |
| Safety | READ ONLY |
| Expected impact | None -- this file is a documentation worksheet and contains no executable statements. |
| Required privileges | Role membership in `pg_monitor` (or `pg_read_all_stats`) is sufficient. No superuser required. |
| Prerequisites | Output from scripts 01-05 of this workflow, plus CloudWatch VolumeBytesUsed history for the same window. |
| Execution order | Step 06 of workflow `storage-and-capacity/capacity-forecasting` |
| Related scripts | None |

## How to interpret / use this runbook

Fill this in at every capacity review and keep the completed copies -- comparing successive forecasts against what actually happened is the only way to learn how wrong the linear model is for your specific workload, and that correction factor is worth more than any refinement to the model itself. Sections 4 and 5 are the ones that matter: the assumptions are what a reviewer should attack, and the runway-to-action mapping is what turns a number into a decision.

---

## Why this worksheet exists

A projection without its assumptions written down next to it is worse than no projection at all, because it gets quoted as a fact and then breaks the first time a market event changes the growth rate. This worksheet is the artifact you attach to the capacity review; the scripts produce numbers, this produces a decision record.

Nothing in this file is executed. It contains no DDL and no statements to run.

## 1. Inputs -- record these with a timestamp

| Input | Source | Value | Captured at |
|---|---|---|---|
| Cluster volume used | CloudWatch `VolumeBytesUsed` | | |
| Sum of logical database sizes | script 01 | | |
| Gap (volume minus logical) | derived | | |
| Top relation by size | script 02 | | |
| Observed growth window length | script 03 / 04 | | |
| Cluster-wide growth rate | script 04 | | |

The gap between cluster volume and logical size is space Aurora has allocated and will never release. Record it every review: a widening gap means deletes are freeing space logically without reducing cost, which changes what remediation is worth doing.

## 2. Thresholds being forecast against

A projection with no threshold produces a number nobody can act on. Agree these before running the forecast, not after seeing it:

| Threshold | Value | Owner | Why this number |
|---|---|---|---|
| Per-relation size limit | | | |
| Cluster volume budget | | | |
| Monthly storage cost ceiling | | | |
| Aurora hard volume limit | 128 TiB | AWS | Engine limit, not negotiable |

## 3. Projection results

| Relation | Size now | Growth/day | Projected at horizon | Days to threshold | Confidence |
|---|---|---|---|---|---|
| | | | | | |

Copy the top ten rows from script 04 (or script 05 if no history exists yet). Carry the `confidence_note` column through verbatim -- it is the single most important column in the table and the first thing a reviewer should see.

## 4. Assumptions -- state them explicitly

Tick each one that this forecast depends on, and note anything known to break it:

- The growth rate observed over the last window continues unchanged.
- No new product, venue listing, instrument, or retention requirement ships inside the horizon. (List any that are planned -- these invalidate the model.)
- No archival, purge, or partition-detach runs inside the horizon. (If one is scheduled, the forecast should be adjusted down by its expected reclaim.)
- Average row width stays constant (relevant only for the script 05 proxy).
- Trading volume follows its recent trend. On an exchange this is the weakest assumption in the list and the one most likely to be wrong.

## 5. Decisions and triage

Map the shortest runway in section 3 to an action:

| Runway | Required action |
|---|---|
| Under 30 days | Escalate now. Too short for any safe structural remediation -- expect a tactical intervention and an AWS conversation. |
| 30-90 days | Schedule remediation immediately. Index cleanup and retention policy are the only levers that fit this window. |
| 90-365 days | Plan a partitioning or archival project this quarter; there is time to do it carefully. |
| Over 365 days | Record and re-review next quarter. |

## 6. Remediation candidates considered

For each, record the expected reclaim, the effort, and the decision:

- Drop unused and duplicate indexes (from the index-growth workflow).
- Attach a retention policy to the largest append-only relation.
- Partition the largest time-series relation so retention becomes a detach.
- Move cold history or wide payload columns out of the OLTP cluster.
- Accept the growth and budget for it (a legitimate decision when growth is genuine revenue-driven volume -- just make it explicitly rather than by default).

## 7. Review

| Field | Value |
|---|---|
| Forecast produced by | |
| Date produced | |
| Horizon used | |
| Next review date | |
| Reviewers | |

Set the next review date no further out than half the shortest runway in section 3. A forecast that outlives its own review cadence is how capacity surprises happen.
