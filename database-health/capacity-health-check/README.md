# Capacity Health Check

**Category:** Database Health Checks | **Workflow:** `database-health/capacity-health-check`

## 1. Problem Description

A focused sweep of storage, connection, and I/O capacity headroom -- distinct from the general checks in comprehensive-health-check and daily-health-check, which touch capacity only in passing. This workflow answers one question specifically: does this cluster have room to keep growing at its current rate before storage, connections, or I/O become the limiting factor? It is the read-only, SQL-level companion to storage-and-capacity/capacity-forecasting, which builds the longer-range trend and projection on top of the same underlying signals.

## 2. Typical Symptoms

- No active symptom -- this is a scheduled capacity review (monthly, or ahead of a known volume event such as a new listing or a derivatives launch).
- Storage cost or CloudWatch VolumeBytesUsed has been trending upward and the team wants a database-level explanation of what is driving it.
- A capacity planning conversation needs current, concrete numbers rather than estimates.

## 3. Business Impact

- Aurora storage grows in increments and never shrinks automatically when rows are deleted; an exchange platform's steadily accumulating trades, ledger_entries, and audit tables mean storage capacity questions compound rather than resolve themselves.
- Connection headroom exhausted during a volatility spike is a binary, all-or-nothing failure: every unserved connection request means matching-engine and withdrawal-processing requests simply fail, at exactly the moment volume and revenue are highest.
- I/O capacity that has quietly become the bottleneck (rather than CPU) is easy to miss because CPU utilization can look comfortable while checkpoint and buffer I/O pressure is already high -- catching this before it becomes latency-visible avoids a harder-to-diagnose incident later.

## 4. Possible Root Causes

- Organic data growth outpacing the storage/retention plan that was sized for a smaller historical volume.
- Retained WAL from an inactive or lagging replication slot silently consuming storage that is not visible in a simple table-size inventory.
- Connection pool sizing across an expanding number of application instances or services approaching the instance class's effective max_connections ceiling.
- Write-heavy workload growth increasing checkpoint frequency and buffer I/O pressure faster than table row counts alone would suggest.
- Temp file spillage growing as query volume grows, consuming local instance storage that is shared with other operations.

## 5. Investigation Strategy

1. Size the database and its largest tables first, to establish which objects are actually driving storage consumption.
2. Check the growth trend if historical snapshots are available, or note that they are not yet being collected.
3. Check connection capacity headroom and its per-application breakdown.
4. Check I/O and checkpoint pressure, since this is the capacity dimension least visible from a simple size inventory.
5. Check replication slots for WAL retention that silently consumes storage outside any table.
6. Check temp file usage and index footprint as secondary storage consumers.
7. Review the key settings that define the current capacity ceiling (max_connections, work_mem, checkpoint tuning).

## 6. Prerequisites

- Role membership in pg_monitor (or pg_read_all_stats).
- The optional table-size history tracking table from automation/growth-monitoring (if deployed) for a real growth-rate calculation; without it, this workflow still produces a single-point-in-time capacity snapshot.
- The cluster's current instance class and provisioned storage configuration, to interpret headroom percentages against actual limits rather than in the abstract.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_database_and_table_footprint.sql`](scripts/01_database_and_table_footprint.sql) -- Sizes every database and the largest tables in the current database.
2. [`scripts/02_table_growth_trend.sql`](scripts/02_table_growth_trend.sql) -- Computes table growth over time from an optional periodic size-history tracking table, if one has been deployed.
3. [`scripts/03_connection_capacity_headroom.sql`](scripts/03_connection_capacity_headroom.sql) -- Measures connection utilization against max_connections and breaks it down by application.
4. [`scripts/04_io_and_checkpoint_pressure.sql`](scripts/04_io_and_checkpoint_pressure.sql) -- Reports per-backend-type I/O statistics and checkpoint/background-writer activity.
5. [`scripts/05_replication_slot_wal_retention.sql`](scripts/05_replication_slot_wal_retention.sql) -- Flags replication slots retaining an unusually large amount of WAL relative to a documented threshold.
6. [`scripts/06_temp_file_and_index_footprint.sql`](scripts/06_temp_file_and_index_footprint.sql) -- Reports cumulative temp file usage per database and the largest indexes in the current database.
7. [`scripts/07_key_capacity_settings.sql`](scripts/07_key_capacity_settings.sql) -- Snapshots the settings that define the current capacity ceiling.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Aurora storage grows in 10GiB increments on the shared cluster volume and is never returned to the pool when rows are deleted or a table is dropped -- pg_database_size()/pg_total_relation_size() show the logical footprint, not the billed volume; use CloudWatch VolumeBytesUsed for the actual billed figure.
- max_connections on Aurora is derived from the instance class via the parameter-group formula rather than freely set -- raising the ceiling requires a larger instance class (or reducing per-service connection counts via pooling), not a simple parameter change.
- Aurora's I/O to the distributed storage layer is billed and capacity-planned separately from compute (see CloudWatch VolumeReadIOPs/VolumeWriteIOPs); a checkpoint/buffer-I/O finding here is a signal to review that CloudWatch data alongside this SQL-level view, not a substitute for it.

## 8. Interpretation Guide

- This is a capacity check, not a performance check: a finding here is 'we are approaching a ceiling', not 'a query is slow right now' -- route performance-shaped findings to the performance/ category instead.
- A single snapshot shows the current state; it cannot show the growth rate. Whenever the growth-trend script has no tracking table available, treat this run as the first of a series and schedule the next one rather than trying to conclude a trend from one data point.
- Connection headroom should be read against the instance class's effective max_connections, not against an assumption of what the value should be -- Aurora derives it from instance memory via the parameter-group formula, so the only way to raise the ceiling is a larger instance class or fewer per-service connections via pooling.
- A replication slot retaining a large amount of WAL is a capacity finding even though it shows up nowhere in a table-size inventory -- it is easy to miss unless checked explicitly.
- Checkpoint and buffer I/O pressure trending upward while CPU utilization looks comfortable is the classic 'we still have headroom' false signal on Aurora, where I/O to the distributed storage layer is a genuinely separate capacity dimension from compute.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- This workflow does not remediate capacity -- it is entirely diagnostic. Any capacity action (retention/archival, instance resize, connection pooling change) is planned and executed through its owning workflow.
- The one exception worth acting on immediately: a replication slot retaining an unexpectedly large amount of WAL from a decommissioned or broken consumer should be investigated and, if genuinely abandoned, removed under change control -- it is pure waste that a table-size inventory would never surface.

**Short-term remediation** (hours to days):

- Open a capacity ticket per finding, ranked by proximity to a hard limit (connections, provisioned IOPS, storage cost trend) rather than by which number looks largest in isolation.
- Hand off storage-growth findings to archival-and-data-lifecycle/investigate-archiving-candidate and connection-headroom findings to connections/max-connections-planning for the detailed remediation path.

**Long-term engineering fix** (days to weeks):

- Deploy the growth-monitoring collector (automation/growth-monitoring) if it is not already running, so future capacity-health-check runs have real trend data instead of single-point snapshots.
- Feed this workflow's findings into storage-and-capacity/capacity-forecasting on a recurring cadence so capacity planning becomes a standing process rather than a reactive one-off review.
- Establish per-instance-class connection and storage headroom thresholds with the platform team ahead of known high-volume events, rather than discovering the ceiling during one.

## 10. Production Safety

- Every script in this workflow is strictly read-only: catalog and statistics views only, no DDL, no DML, and no VACUUM/ANALYZE.
- Safe to run at any time, including during peak trading; the heaviest step is the table/index size inventory, which scales with the number of relations in the schema but takes no locks beyond brief catalog access.
- Safe to run on a reader instance for the sizing and settings steps; run the connection and I/O steps against the writer, since those statistics are per-instance.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Connection utilization above 85% with no clear path to reduce per-service pool sizes -- escalate to connections/max-connections-planning before the next high-volume event.
- A replication slot retaining tens of gigabytes or more of WAL with no active consumer -- escalate immediately, this is unattributed storage growth with a clear owner question attached.
- Storage growth on a table not explained by expected business volume (a reference or configuration table appearing among the largest tables) -- escalate to investigate a bug or unintended accumulation.
- Checkpoint or buffer I/O pressure rising for several consecutive reviews while row counts alone do not explain the increase -- escalate to storage-and-capacity/wal-generation.

## 12. Related Issues

- [comprehensive-health-check](../comprehensive-health-check/README.md)
- [daily-health-check](../daily-health-check/README.md)
- [capacity-forecasting](../../storage-and-capacity/capacity-forecasting/README.md)
- [database-growth](../../storage-and-capacity/database-growth/README.md)
- [max-connections-planning](../../connections/max-connections-planning/README.md)
- [investigate-archiving-candidate](../../archival-and-data-lifecycle/investigate-archiving-candidate/README.md)
