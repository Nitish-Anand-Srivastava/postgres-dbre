# REINDEX CONCURRENTLY Campaign Planning

**Category:** Maintenance | **Workflow:** `maintenance/reindex-strategy`

## 1. Problem Description

Plans a batched, off-peak REINDEX CONCURRENTLY campaign across multiple bloated indexes in a cluster -- distinct from schema-changes/concurrent-index-build's single-index build guidance, this workflow is about sequencing and monitoring a multi-index campaign safely.

## 2. Typical Symptoms

- index-bloat/routine-maintenance-checklist findings identify multiple bloated indexes across several tables that need rebuilding.
- A large batch of indexes has not been rebuilt since initial creation and bloat has accumulated over months of write traffic.

## 3. Business Impact

- Rebuilding many indexes without a plan (all at once, during peak hours, without monitoring) risks compounding I/O/CPU load across the cluster at the worst possible time; a planned, batched, off-peak campaign gets the same space/performance benefit without that risk.

## 4. Possible Root Causes

- Indexes accumulate bloat over time from update/delete churn the same way tables do, but unlike table bloat (addressed continuously by autovacuum), PostgreSQL has no automatic index-bloat reclamation -- REINDEX (or an equivalent extension-based tool) is the only way to reclaim it.
- A cluster that has never had a standing reindex cadence accumulates a large backlog that then requires a deliberate campaign rather than one-off maintenance.

## 5. Investigation Strategy

1. Identify and rank candidate indexes by size/bloat and usage, to sequence the campaign by highest-value target first.
2. Check for any REINDEX (or CREATE INDEX CONCURRENTLY) already in progress before starting another, since concurrent index-maintenance operations compete for maintenance_work_mem and I/O.
3. Plan batch size and off-peak scheduling before starting, rather than reacting index-by-index.

## 6. Prerequisites

- Table-owner privilege (or pg_maintain membership) on every index's parent table; an off-peak maintenance window agreed with stakeholders for a multi-index campaign on a high-traffic cluster.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_reindex_candidate_ranking.sql`](scripts/01_reindex_candidate_ranking.sql) -- Ranks indexes by size and usage to sequence the campaign, reusing the same bloat/usage view as the routine checklist.
2. [`scripts/02_reindex_progress_monitor.sql`](scripts/02_reindex_progress_monitor.sql) -- Monitors live progress of any REINDEX CONCURRENTLY (or CREATE INDEX CONCURRENTLY) currently running, to confirm each batch is progressing before starting the next.
3. [`scripts/03_reindex_concurrently_runbook.md`](scripts/03_reindex_concurrently_runbook.md) -- Guarded runbook for executing a batched REINDEX CONCURRENTLY campaign across the candidates identified in script 01.

## 8. Interpretation Guide

- REINDEX CONCURRENTLY (available since PostgreSQL 12) avoids the exclusive lock a plain REINDEX takes, at the cost of roughly double the disk space during the rebuild (old and new index coexist briefly) and a longer overall duration than the blocking form -- sequencing indexes one at a time, or a few at a time bounded by available disk headroom, avoids running out of space mid-campaign.
- pg_stat_progress_create_index reports REINDEX CONCURRENTLY's progress under the same view as CREATE INDEX CONCURRENTLY (the `command` column distinguishes them) -- a build parked in a 'waiting for ...' phase is blocked on another transaction finishing, not on I/O, and no amount of extra maintenance_work_mem will speed that up.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- N/A -- this is a planned maintenance workflow, not an incident response.

**Short-term remediation** (hours to days):

- Execute the campaign in the planned batches, monitoring each batch's progress before starting the next.

**Long-term engineering fix** (days to weeks):

- Establish a standing reindex cadence (e.g. as part of routine-maintenance-checklist) so bloat is addressed incrementally going forward instead of requiring another large one-off campaign.

## 10. Production Safety

- The investigation/monitoring scripts here are read-only. The REINDEX CONCURRENTLY campaign itself is a guarded, manual runbook -- it takes a SHARE UPDATE EXCLUSIVE lock (blocks other DDL and VACUUM on the table, but not ordinary reads/writes) and requires roughly double the index's disk space during the rebuild.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Available disk headroom on the cluster is not comfortably larger than the single largest candidate index's current size -- escalate for a capacity check (storage-and-capacity/capacity-forecasting) before starting the campaign, since REINDEX CONCURRENTLY needs to build the full new index before dropping the old one.

## 12. Related Issues

- [index-bloat](../../tables-and-indexes/index-bloat/README.md)
- [concurrent-index-build](../../schema-changes/concurrent-index-build/README.md)
- [routine-maintenance-checklist](../routine-maintenance-checklist/README.md)
