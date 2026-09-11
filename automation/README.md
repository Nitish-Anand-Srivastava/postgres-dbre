# Automation

**Category:** `automation`

This is the index for the `automation/` category: every workflow
(issue directory) below addresses a distinct, real operational problem or
DBA use case for this Aurora PostgreSQL toolkit, per the repository's
one-parent-directory-per-problem design. Each workflow directory is
self-contained -- its own `README.md` (problem description, symptoms,
business impact, root causes, investigation strategy, prerequisites,
interpretation guide, remediation options, production safety, and
escalation criteria) and a `scripts/` directory of numbered, read-only-by
-default investigation scripts (see each workflow's `scripts/README.md`
for the full script-by-script execution table).

## Workflows

| Workflow | Summary |
| --- | --- |
| [`health-checks`](health-checks/README.md) | Documents how to run the database-health/ workflows (daily-health-check, comprehensive-health-check, capacity-health-check, and the pre/post-deployment and pre/post-maintenance checks) on a recurring, unattended schedule instead of manually and inconsistently. Two scheduling mechanisms are covered: `pg_cron` running inside the database when it is enabled on the cluster parameter group, and an external scheduler (an AWS Lambda function on an EventBridge/CloudWatch Events cron rule, invoking the database via the RDS Data API or a network path to the writer) when it is not. This workflow itself performs no scheduling -- it is diagnostic (does pg_cron already have jobs registered) and documentary (how to add more), never an auto-executing setup step. |
| [`growth-monitoring`](growth-monitoring/README.md) | This is the authoritative home for the optional dba_toolkit.table_size_history tracking table that tables-and-indexes/rapidly-growing-tables and storage-and-capacity's growth/forecasting workflows already reference and depend on for a genuine growth-rate calculation -- every one of them detects this table's absence via to_regclass() and points back here. Without it, every growth-related workflow in this toolkit can only report a single point-in-time size, never an actual rate. This workflow documents the collector's schema, its periodic population job, and provides read-only scripts to confirm it is deployed and collecting on a healthy cadence. |
| [`xid-monitoring`](xid-monitoring/README.md) | The automated, scheduled counterpart to transactions-and-xid/transaction-age's manual database- and table-level XID age snapshots. Transaction ID wraparound risk is exactly the kind of slow-burning problem that a manual, occasionally-remembered check will eventually miss -- this workflow documents running the same read-only age checks on a recurring schedule with alert thresholds set well below the emergency failsafe, so a climbing trend is caught weeks before it becomes urgent. |
| [`index-monitoring`](index-monitoring/README.md) | The automated, scheduled counterpart to tables-and-indexes/unused-indexes and tables-and-indexes/invalid-indexes -- and to storage-and-capacity/index-growth's usage-context review. Index accretion (indexes added one at a time to fix individual slow queries, never reviewed as a set) is a slow, easy-to-miss trend; this workflow documents capturing unused, invalid, and usage/size context on a recurring schedule so the trend is visible before an ad-hoc cleanup project is the only option left. |
| [`capacity-monitoring`](capacity-monitoring/README.md) | The automated, scheduled counterpart to storage-and-capacity/capacity-forecasting and database-health/capacity-health-check -- both of which are, by design, point-in-time or manually-triggered reviews. This workflow documents capturing the same storage, connection, and I/O capacity signals on a recurring schedule with threshold-based alerting, so a capacity ceiling (storage cost trajectory, connection headroom, I/O pressure) is flagged automatically as it is approached, rather than only discovered at the next manually-triggered review. |

## Related Categories

- [`connections/max-connections-planning`](../../connections/max-connections-planning/README.md)
- [`database-health/capacity-health-check`](../../database-health/capacity-health-check/README.md)
- [`database-health/comprehensive-health-check`](../../database-health/comprehensive-health-check/README.md)
- [`database-health/daily-health-check`](../../database-health/daily-health-check/README.md)
- [`storage-and-capacity/capacity-forecasting`](../../storage-and-capacity/capacity-forecasting/README.md)
- [`storage-and-capacity/index-growth`](../../storage-and-capacity/index-growth/README.md)
- [`storage-and-capacity/table-growth`](../../storage-and-capacity/table-growth/README.md)
- [`tables-and-indexes/invalid-indexes`](../../tables-and-indexes/invalid-indexes/README.md)
- [`tables-and-indexes/rapidly-growing-tables`](../../tables-and-indexes/rapidly-growing-tables/README.md)
- [`tables-and-indexes/unused-indexes`](../../tables-and-indexes/unused-indexes/README.md)
- [`transactions-and-xid/transaction-age`](../../transactions-and-xid/transaction-age/README.md)
- [`transactions-and-xid/xid-wraparound-risk`](../../transactions-and-xid/xid-wraparound-risk/README.md)

Start with the workflow whose title most closely matches the symptom you are
investigating; if uncertain, `database-health/comprehensive-health-check`
and `incident-response/production-triage` both provide a broad first pass
that surfaces which specific workflow to open next.
