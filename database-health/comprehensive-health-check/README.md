# Comprehensive Database Health Check

**Category:** Database Health Checks | **Workflow:** `database-health/comprehensive-health-check`

## 1. Problem Description

A single, end-to-end read-only sweep of every dimension of Aurora PostgreSQL health that can silently degrade a crypto-exchange platform: sizing and growth, connection headroom, open transaction horizon, locking, dead tuples and vacuum progress, transaction ID age, query hot spots, temporary file spills, index usage, and reader replication health. This is the deep quarterly/ad-hoc assessment, the first thing to run when taking over an unfamiliar cluster, and the evidence pack to attach to an incident review -- not the lightweight daily loop (see daily-health-check for that).

## 2. Typical Symptoms

- No specific active symptom is required -- this workflow is run proactively, on cluster handover, before a major trading event (token listing, scheduled derivatives expiry, marketing campaign), or as the evidence-gathering pass after an incident.
- A vague, hard-to-localize report such as 'the exchange feels slower this week' with no single obvious failing subsystem.
- An audit or compliance review requires a documented, point-in-time statement of database health for the order, ledger, and settlement stores.

## 3. Business Impact

- Health problems on an exchange cluster are rarely visible until they are urgent: XID age climbing toward wraparound, a replication slot silently retaining WAL, or a bloating ledger table will each eventually convert into a trading halt rather than a gradual slowdown.
- Catching connection-headroom exhaustion before it happens prevents the failure mode where matching-engine and withdrawal-processing services cannot open a connection at exactly the moment volatility spikes and volume is highest.
- A documented baseline of 'what healthy looks like' shortens every future incident: without it, the on-call DBA cannot distinguish an abnormal reading from this cluster's normal operating profile.

## 4. Possible Root Causes

- Capacity drift: steady organic growth of trades, ledger_entries, and order_book_snapshots gradually consuming the headroom that was sized for last year's volume.
- Configuration drift: parameter-group changes, per-table autovacuum overrides, or work_mem tuning applied during an incident and never reviewed afterwards.
- Workload drift: a new API endpoint, market-data consumer, or reconciliation job introducing query shapes that were never capacity-planned.
- Maintenance debt: autovacuum falling behind on the highest-churn tables, stale planner statistics after a backfill, or invalid indexes left behind by a failed concurrent build.
- Operational debt: an abandoned logical replication slot from a decommissioned CDC pipeline, or a forgotten prepared transaction holding back the vacuum horizon indefinitely.

## 5. Investigation Strategy

1. Establish context first: which instance am I on (writer or reader), what engine version, and how long has it been up since the last failover or reboot?
2. Size the system: database and table footprint, so every later finding can be judged in proportion.
3. Check the cheap, high-signal cluster-wide counters (cache hit ratio, rollback ratio, deadlocks, temp files) before drilling into anything specific.
4. Check connection headroom, because exhausting it makes every other remediation harder to apply.
5. Check the open transaction horizon (long transactions and prepared transactions), since one old snapshot invalidates conclusions drawn from vacuum and bloat data.
6. Check locking, vacuum/dead tuples, and transaction ID age -- the three maintenance-health pillars.
7. Check query-level hot spots and temp file spills to connect database state back to application behavior.
8. Check index usage and, finally, reader/replication health so the whole cluster (not just the writer) is covered.
9. Record the output of every step with a timestamp; the value of this workflow compounds only if successive runs can be compared.

## 6. Prerequisites

- Role membership in pg_monitor (or pg_read_all_stats) on the target database.
- pg_stat_statements installed for the query-level step (the script degrades gracefully with a notice if it is absent).
- A place to store the output (ticket, runbook log, or object storage) so this run becomes a comparable baseline rather than a throwaway.
- Knowledge of when statistics were last reset -- every cumulative counter in this workflow is 'since stats_reset', and an Aurora failover or a manual pg_stat_reset() silently restarts that window.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_instance_identity_and_uptime.sql`](scripts/01_instance_identity_and_uptime.sql) -- Establishes which instance, engine version, and role this session is connected to, and how long the instance has been up.
2. [`scripts/02_database_and_table_sizes.sql`](scripts/02_database_and_table_sizes.sql) -- Captures the logical footprint of every database and the largest tables in the current database.
3. [`scripts/03_database_activity_counters.sql`](scripts/03_database_activity_counters.sql) -- Cluster-wide throughput, cache efficiency, rollback ratio, deadlock, and temp file counters per database.
4. [`scripts/04_connection_headroom_and_state.sql`](scripts/04_connection_headroom_and_state.sql) -- Measures connection utilization against max_connections and breaks current sessions down by database and state.
5. [`scripts/05_open_transaction_horizon.sql`](scripts/05_open_transaction_horizon.sql) -- Identifies the oldest open transactions and any outstanding prepared (two-phase commit) transactions.
6. [`scripts/06_blocking_and_lock_waits.sql`](scripts/06_blocking_and_lock_waits.sql) -- Checks for sessions currently blocked on locks and identifies which sessions are blocking them.
7. [`scripts/07_dead_tuples_and_vacuum_status.sql`](scripts/07_dead_tuples_and_vacuum_status.sql) -- Ranks tables by dead tuple volume and shows when each was last vacuumed or analyzed.
8. [`scripts/08_autovacuum_activity.sql`](scripts/08_autovacuum_activity.sql) -- Shows autovacuum and manual VACUUM workers running right now, with their progress phase.
9. [`scripts/09_transaction_id_age.sql`](scripts/09_transaction_id_age.sql) -- Measures transaction ID age per database against the wraparound-protection thresholds.
10. [`scripts/10_top_queries_by_total_time.sql`](scripts/10_top_queries_by_total_time.sql) -- Ranks normalized statements by cumulative execution time to show where the database actually spends its time.
11. [`scripts/11_temp_file_usage.sql`](scripts/11_temp_file_usage.sql) -- Reports cumulative temporary file creation per database, indicating sorts and hashes spilling to disk.
12. [`scripts/12_index_usage_overview.sql`](scripts/12_index_usage_overview.sql) -- Inventories index size and scan activity to reveal both unused indexes and heavily relied-upon ones.
13. [`scripts/13_replication_and_reader_health.sql`](scripts/13_replication_and_reader_health.sql) -- Reports Aurora cluster replica status and lag from the Aurora-native status function.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Aurora readers are not standard streaming replicas: they replay redo from the shared storage volume, so pg_stat_replication is empty on an Aurora writer even when readers exist and are healthy. Reader lag must be read from aurora_replica_status() or the CloudWatch AuroraReplicaLag metric.
- An Aurora failover resets in-memory statistics on the promoted instance: pg_stat_database, pg_stat_statements, pg_stat_wal, and pg_stat_checkpointer all restart their accumulation window. Check instance uptime (script 01) before comparing counters against a previous run.
- Logical database size as reported by pg_database_size() is not the billed Aurora storage figure -- the cluster volume grows in increments and does not shrink when rows are deleted. Use CloudWatch VolumeBytesUsed for the storage-cost view and these queries for the logical view.
- Aurora does not support ALTER SYSTEM for most parameters: every configuration finding from this sweep is remediated through the DB cluster or DB instance parameter group, and some changes require a reboot to take effect.

## 8. Interpretation Guide

- Nothing in this workflow is judged against a universal 'good' number: interpret every value against this cluster's own previous run and against the business cycle (a Monday-morning reading is not comparable to a weekend reading on an exchange).
- Cumulative counters (xact_commit, blks_hit, temp_files, deadlocks, idx_scan) are meaningless as absolutes -- always divide by the time since stats_reset, or diff two runs, to get a rate.
- A cache hit ratio below roughly 99% on an OLTP exchange workload usually means the working set no longer fits in shared_buffers; on Aurora this matters more than on community PostgreSQL because a buffer miss becomes a network round trip to the distributed storage layer rather than a local page read.
- One old transaction explains a surprising number of simultaneous 'problems' (rising dead tuples, unremovable bloat, growing XID age, lock waits). Always resolve the oldest-transaction finding before concluding anything about vacuum health.
- Findings that look alarming in isolation are often expected for an exchange: a high seq_scan count on a small markets/instruments reference table, or a high dead tuple count on an orders table between vacuum cycles, are both normal.
- If the instance restarted or failed over recently (script 01), most cumulative counters have been reset and this run is a fresh baseline, not a comparison point.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Triage only what this sweep shows as actively dangerous right now: connection utilization above ~85%, XID age above ~50% of autovacuum_freeze_max_age, a blocking chain on ledger/wallet tables, or a prepared transaction older than a few minutes.
- For each such finding, hand off to the dedicated workflow rather than improvising here -- this workflow deliberately stops at detection.

**Short-term remediation** (hours to days):

- Open a ticket per finding with the captured output attached, ranked by proximity to a hard limit (connections, XID age, storage) rather than by how unusual the number looks.
- Re-run the specific sub-check after each remediation so the ticket carries before/after evidence.
- Schedule targeted vacuum/analyze for the specific tables this sweep flagged, instead of a blanket database-wide maintenance pass.

**Long-term engineering fix** (days to weeks):

- Automate this sweep on a schedule and persist the results, so growth and drift become a trend line rather than a series of disconnected snapshots.
- Promote the checks that repeatedly find real problems on this cluster into the daily-health-check loop, and the ones that never fire into a quarterly cadence.
- Feed the capacity findings (storage growth, connection headroom) into the platform capacity plan ahead of known volume events such as a new listing or a derivatives launch.

## 10. Production Safety

- Every script in this workflow is strictly read-only: catalog and statistics views only, no DDL, no DML, no session termination, and no ANALYZE/VACUUM of any table.
- All scripts execute unmodified on a connection with default_transaction_read_only = on, which makes them safe to run against the writer during an active incident.
- Safe to run on a reader instance, with one caveat: pg_stat_activity, pg_locks, and the statistics counters are per-instance, so a reader shows only that reader's own sessions and activity -- run the connection, lock, and query steps on the writer when investigating writer-side behavior.
- The heaviest step is the index/size inventory, which reads pg_class and relation-size functions for every relation; on a schema with tens of thousands of partitions this can take several seconds. It still takes no locks beyond brief catalog access.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- XID age above 1,000,000,000 in any database, or above 50% of autovacuum_freeze_max_age and still rising between two runs -- escalate immediately to transactions-and-xid/xid-wraparound-risk.
- Connection utilization above 90% of max_connections on the writer -- escalate to connections/connection-exhaustion before it becomes a full outage.
- A prepared transaction older than a few minutes, or a replication slot retaining tens of gigabytes of WAL -- both silently block cleanup cluster-wide and need an owner identified immediately.
- Any finding that implicates the ledger, wallet, or settlement tables' correctness (not just their performance) -- escalate to database engineering and the finance/treasury on-call together.

## 12. Related Issues

- [daily-health-check](../daily-health-check/README.md)
- [capacity-health-check](../capacity-health-check/README.md)
- [pre-deployment-check](../pre-deployment-check/README.md)
- [high-database-load](../../performance/high-database-load/README.md)
- [xid-wraparound-risk](../../transactions-and-xid/xid-wraparound-risk/README.md)
- [autovacuum-not-keeping-up](../../vacuum-and-autovacuum/autovacuum-not-keeping-up/README.md)
- [connection-exhaustion](../../connections/connection-exhaustion/README.md)
- [replication-health](../../replication-and-ha/replication-health/README.md)
