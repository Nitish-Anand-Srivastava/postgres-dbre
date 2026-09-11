# Table Growth History Collector

**Category:** Automation | **Workflow:** `automation/growth-monitoring`

## 1. Problem Description

This is the authoritative home for the optional dba_toolkit.table_size_history tracking table that tables-and-indexes/rapidly-growing-tables and storage-and-capacity's growth/forecasting workflows already reference and depend on for a genuine growth-rate calculation -- every one of them detects this table's absence via to_regclass() and points back here. Without it, every growth-related workflow in this toolkit can only report a single point-in-time size, never an actual rate. This workflow documents the collector's schema, its periodic population job, and provides read-only scripts to confirm it is deployed and collecting on a healthy cadence.

## 2. Typical Symptoms

- A growth or capacity-forecasting workflow's script reports that dba_toolkit.table_size_history does not exist.
- Capacity planning is currently limited to single-point-in-time size snapshots with no way to compute an actual growth rate.
- The collector was deployed at some point but nobody has confirmed it is still running.

## 3. Business Impact

- Every day this collector is not deployed is a day of trend data that cannot be reconstructed retroactively -- the earlier it is deployed, the sooner every growth/capacity-forecasting workflow in this toolkit becomes genuinely useful instead of limited to point-in-time snapshots.
- A collector that silently stops running (a dropped pg_cron job, a failed scheduled task) produces the same 'no history available' outcome as never having deployed it, but is far more likely to go unnoticed because the table still exists.

## 4. Possible Root Causes

- N/A -- this is an infrastructure-deployment and monitoring workflow, not an incident investigation.

## 5. Investigation Strategy

1. Check whether the tracking table already exists and, if so, how many rows it has and when it was last populated.
2. If it exists, check for gaps in the collection cadence -- a table that exists but stopped being populated months ago is effectively the same problem as one that was never deployed.
3. If it does not exist, or has an unhealthy cadence, deploy or repair the collector using the runbook in this workflow.

## 6. Prerequisites

- `pg_monitor` role membership (or `pg_read_all_stats`) for the read-only status checks.
- For deployment: a role with `CREATE` privilege on the target database (to create the `dba_toolkit` schema and table) and, if scheduling via pg_cron, the prerequisites in automation/health-checks.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_check_tracking_table_status.sql`](scripts/01_check_tracking_table_status.sql) -- Checks whether dba_toolkit.table_size_history already exists and, if so, reports its row count and capture window.
2. [`scripts/02_verify_collection_cadence.sql`](scripts/02_verify_collection_cadence.sql) -- Where the tracking table exists, checks for gaps between consecutive capture timestamps to confirm the collector is running on a healthy, consistent cadence.
3. [`scripts/03_growth_rate_from_history.sql`](scripts/03_growth_rate_from_history.sql) -- The payoff query: computes actual per-table growth over the retention window from the collected history, which is the whole reason the collector exists.
4. [`scripts/04_deploy_collector_runbook.md`](scripts/04_deploy_collector_runbook.md) -- Documents the exact DDL for dba_toolkit.table_size_history and the periodic collector job that populates it -- deliberate, reviewed infrastructure you deploy once, not something to pipe into psql unread.

## 8. Interpretation Guide

- A tracking_table_exists = false result from script 01 is not a failure of this workflow -- it is the expected state before the collector has ever been deployed. Proceed to the runbook in script 04.
- A tracking table that exists but whose latest_capture_at is far in the past (days, for a collector intended to run hourly or daily) means the collector has stopped running -- check the scheduling mechanism (pg_cron job status via automation/health-checks, or the external scheduler's own logs) rather than assuming the table itself needs fixing.
- distinct_tables_tracked growing over time as new tables are created is expected and healthy; a sudden drop suggests the collector's population query is filtering more narrowly than intended (e.g. a schema exclusion that now excludes a schema it should not).

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- N/A -- this workflow is diagnostic and documentary. If the collector has stopped running, its scheduling mechanism (pg_cron job, external scheduled task) is the thing to repair, not this workflow itself.

**Short-term remediation** (hours to days):

- Deploy the collector following the runbook in this workflow if it does not exist yet, so the earliest possible baseline snapshot is captured today rather than after further delay.

**Long-term engineering fix** (days to weeks):

- Add a retention/pruning policy to the collector's own scheduled job (delete rows older than a documented retention window, e.g. 13 months) so the tracking table itself does not become an unbounded-growth problem.
- Monitor the collector's own pg_cron job run history (see automation/health-checks) so a silently-stopped collector is caught quickly rather than discovered the next time someone needs a growth rate.

## 10. Production Safety

- The two `.sql` scripts in this workflow are strictly read-only.
- The deployment runbook (script 04) contains DDL and a scheduled INSERT job -- it is markdown, deliberately never an auto-executing script, and must be reviewed and applied by an operator.
- The collector's own periodic INSERT is lightweight (one row per tracked relation per collection interval) and its read query (`pg_total_relation_size()` per relation) is the same catalog-only read every other sizing script in this toolkit already performs.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- The collector has been down (no new rows) for long enough that a business-critical capacity decision cannot be made from trend data -- treat the immediate priority as restoring collection, and fall back to storage-and-capacity's single-point-in-time scripts for the decision at hand.

## 12. Related Issues

- [health-checks](../health-checks/README.md)
- [xid-monitoring](../xid-monitoring/README.md)
- [rapidly-growing-tables](../../tables-and-indexes/rapidly-growing-tables/README.md)
- [table-growth](../../storage-and-capacity/table-growth/README.md)
- [capacity-forecasting](../../storage-and-capacity/capacity-forecasting/README.md)
