# Automation

Scheduled/recurring counterparts to the manual, on-demand investigation
workflows found elsewhere in this repository. Every workflow here documents
how to turn a point-in-time investigation into a durable, periodically-run
check -- via `pg_cron` (if enabled on the cluster's parameter group) or an
externally-scheduled job (Lambda on a CloudWatch Events/EventBridge
schedule, an orchestrator such as Airflow, etc.).

None of the deployment/scheduling steps in this category execute
automatically: every workflow's actual "set this up" step is a guarded,
manually-reviewed markdown runbook (never an auto-running `.sql` file), and
every read-only `.sql` script that depends on optional infrastructure (the
`dba_toolkit` schema, `pg_cron`) detects its absence and returns an
explanatory notice instead of failing.

## Workflows

| Workflow | Automates | Summary |
| --- | --- | --- |
| [`health-checks`](health-checks/README.md) | `database-health/*` | Documents how to run the database-health/ workflows (daily-health-check, comprehensive-health-check, capacity-health-check, and the pre/post-deployment and pre/post-maintenance checks) on a recurring, unattended schedule. |
| [`growth-monitoring`](growth-monitoring/README.md) | `tables-and-indexes/rapidly-growing-tables`, `storage-and-capacity/*` | The authoritative home for the optional `dba_toolkit.table_size_history` tracking table that several other workflows reference and depend on for growth-over-time history. |
| [`xid-monitoring`](xid-monitoring/README.md) | `transactions-and-xid/transaction-age` | The automated, scheduled counterpart to transaction ID age's manual database- and table-level snapshots, so wraparound risk is caught trending upward long before it becomes an incident. |
| [`index-monitoring`](index-monitoring/README.md) | `tables-and-indexes/unused-indexes`, `tables-and-indexes/invalid-indexes` | The automated, scheduled counterpart to unused/invalid-index review and index-growth's usage-context review. |
| [`capacity-monitoring`](capacity-monitoring/README.md) | `storage-and-capacity/capacity-forecasting`, `database-health/capacity-health-check` | The automated, scheduled counterpart to storage/connection/IOPS capacity threshold review. |

## Related categories

* [`database-health/comprehensive-health-check`](../database-health/comprehensive-health-check/README.md) -- the point-in-time check this category's `health-checks` workflow schedules.
* [`storage-and-capacity/capacity-forecasting`](../storage-and-capacity/capacity-forecasting/README.md) -- the growth/capacity workflow `capacity-monitoring` automates.
* [`observability/cloudwatch`](../observability/cloudwatch/README.md) -- CloudWatch alerting that complements (and for infrastructure-level metrics, reduces the need for) database-side scheduled SQL checks.
