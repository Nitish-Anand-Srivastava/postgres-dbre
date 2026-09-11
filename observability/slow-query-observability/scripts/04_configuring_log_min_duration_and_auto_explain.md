# 04_configuring_log_min_duration_and_auto_explain

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `04_configuring_log_min_duration_and_auto_explain.md` |
| Purpose | Runbook for configuring log_min_duration_statement and auto_explain through Aurora's DB parameter group model. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Any instance (writer or reader) |
| Safety | LOW RISK WRITE (Aurora DB parameter group change; log_min_duration_statement typically applies without a reboot, auto_explain's shared_preload_libraries entry requires one -- see runbook) |
| Expected impact | Increases log volume and CloudWatch Logs ingestion cost proportional to the chosen threshold; auto_explain with log_analyze adds real per-statement overhead for statements that cross the threshold. |
| Required privileges | IAM permission to modify the DB cluster/instance parameter group (rds:ModifyDBClusterParameterGroup or console equivalent); no PostgreSQL role required for the parameter-group steps. |
| Prerequisites | Agreement with the platform/logging team on the log volume budget before applying a low threshold cluster-wide. |
| Execution order | Step 04 of workflow `observability/slow-query-observability` |
| Related scripts | ../../performance/slow-queries/README.md |

## How to interpret / use this runbook

Follow this runbook when standing up statement-level logging for the first time, or when tuning an existing threshold that is producing too much or too little log volume. None of the AWS CLI examples here are SQL statements this repository executes -- they are documented AWS-side change steps for the operator to review and run deliberately.

---

## Why pg_stat_statements alone is not enough

pg_stat_statements aggregates by normalized query shape and does not retain
the exact parameter values or the actual execution plan used for a specific
slow occurrence. `log_min_duration_statement` and `auto_explain` fill that
gap by logging the full statement (with parameters) and, optionally, the
real execution plan, whenever a statement exceeds a duration threshold.

## Aurora's parameter-group model (read before changing anything)

Aurora PostgreSQL does not support `ALTER SYSTEM` for most parameters,
including these logging settings. They are configured through the DB
cluster parameter group (cluster-wide defaults) or DB instance parameter
group (writer/reader-specific overrides), applied via the AWS Console, CLI,
or infrastructure-as-code -- never through a SQL session:

```
aws rds modify-db-cluster-parameter-group \
  --db-cluster-parameter-group-name <parameter-group-name> \
  --parameters "ParameterName=log_min_duration_statement,ParameterValue=1000,ApplyMethod=immediate"
```

`log_min_duration_statement` and `auto_explain.log_min_duration` typically
apply without a reboot (dynamic parameters); confirm the specific
parameter's `ApplyType` in `describe-db-cluster-parameters` before assuming
so, since this can change between engine versions.

## Choosing a threshold

Start conservative on a high-throughput exchange writer: a threshold set
far below the workload's normal latency profile generates log volume
proportional to *most* queries, which is itself an I/O and log-ingestion
cost and can obscure the genuinely slow outliers in noise. A reasonable
starting point is the current p99 latency for the busiest transactional
path, reviewed and tightened over time as the log volume proves manageable.

## Enabling auto_explain for real execution plans

`auto_explain` requires `shared_preload_libraries` to include it at the
cluster parameter group level (a reboot-requiring change, unlike the
duration threshold itself). Once loaded, enable it with:

```
aws rds modify-db-cluster-parameter-group \
  --db-cluster-parameter-group-name <parameter-group-name> \
  --parameters "ParameterName=auto_explain.log_min_duration,ParameterValue=1000,ApplyMethod=immediate" \
                "ParameterName=auto_explain.log_analyze,ParameterValue=1,ApplyMethod=immediate"
```

`auto_explain.log_analyze` runs the equivalent of `EXPLAIN (ANALYZE)` for
every statement crossing the threshold, which adds real overhead to those
specific statements (timing instrumentation, not just plan capture) --
enable it deliberately, at a threshold high enough that it only fires for
statements already confirmed slow, not as a blanket setting.

## Retrieving the logged output

Aurora ships PostgreSQL log output to CloudWatch Logs (the log group named
for the DB instance) -- there is no local filesystem log access. Query it
via CloudWatch Logs Insights, or export it to the same pipeline the rest of
this repository's observability recommendations (dashboard-recommendations)
assume.
