# Scripts: CloudWatch Metrics for Aurora PostgreSQL

Execution order, safety classification, and expected runtime for every script
in `observability/cloudwatch/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_sql_side_capacity_and_load_snapshot.sql` | One-row SQL-side snapshot mapped to key CloudWatch metrics. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_replication_lag_sql_companion.sql` | Aurora cluster replica status and lag, per reader. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_cloudwatch_metric_to_sql_mapping.md` | Reference: CloudWatch metric to SQL-level companion query mapping. | INFORMATIONAL -- NO SQL EXECUTED, AWS CONSOLE/API GUIDANCE ONLY (reference mapping; any CloudWatch alarm change is a change-managed AWS action) | A few minutes to read; the referenced SQL scripts are each low runtime individually. |

## Execution Order

Run scripts strictly in the numeric order shown above. Each script assumes the
operator has reviewed the output of the prior step. Do not skip ahead to a
remediation template (`.md` files, if present) without completing the
read-only investigation steps first.

## Required Permissions

Unless a script states otherwise in its `REQUIRED PRIVILEGES` header field, a
role with the built-in `pg_monitor` (or `pg_read_all_stats` /
`pg_read_all_settings`) attribute, `CONNECT` on the target database, and
`USAGE` on `public` is sufficient. Scripts that read `pg_stat_statements`
require that extension to be installed in the current database. Scripts that
touch DDL, `pg_terminate_backend()`, or write operations state elevated
requirements explicitly in their own header.

## Expected Output

Every script returns a result set intended to be read directly in `psql` (or
any SQL client). Columns are named for direct interpretation; each script's
header contains a `HOW TO INTERPRET RESULTS` section, and the parent
`README.md` section 8 ("Interpretation Guide") gives workflow-level guidance.

## When to Stop and Escalate

- AuroraReplicaLag sustained above the application's read-your-own-write tolerance -- escalate to replication-and-ha/reader-lag-investigation.
- BufferCacheHitRatio trending down over successive days with no corresponding traffic explanation -- escalate to performance/high-iops or database-health/capacity-health-check.
- DatabaseConnections approaching max_connections with the SQL-side connections/max-connections-planning headroom check confirming the same -- escalate immediately, this is a hard ceiling with no graceful degradation.
- VolumeBytesUsed growing faster than the documented business growth rate with no SQL-side table growth explaining the difference -- escalate to storage-and-capacity/unexpected-storage-growth to check for retained WAL or an orphaned replication slot.

## Scripts That Should Not Be Run During Severe Incidents

- 03_cloudwatch_metric_to_sql_mapping.md -- None -- this is reference/planning documentation, not an executable script. Any AWS-side action it describes (enabling a feature, creating an alarm) is called out explicitly and is a change-managed action outside this repository's SQL scope.
