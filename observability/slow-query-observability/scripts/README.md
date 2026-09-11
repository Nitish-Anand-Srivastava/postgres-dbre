# Scripts: Building Durable Slow-Query Observability

Execution order, safety classification, and expected runtime for every script
in `observability/slow-query-observability/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_top_statements_by_total_time.sql` | Top statements by cumulative execution time (pg_stat_statements). | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_top_statements_by_mean_time.sql` | Top statements by mean execution time, minimum call count enforced (pg_stat_statements). | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_temp_file_and_io_heavy_statements.sql` | Top statements by temp file and shared-buffer I/O volume (pg_stat_statements). | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_configuring_log_min_duration_and_auto_explain.md` | Runbook: configure log_min_duration_statement / auto_explain via the Aurora parameter group. | LOW RISK WRITE (Aurora DB parameter group change; log_min_duration_statement typically applies without a reboot, auto_explain's shared_preload_libraries entry requires one -- see runbook) | Minutes to apply; dynamic parameters take effect without a restart, auto_explain's preload-library entry requires a reboot the first time it is added. |

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

- pg_stat_statements is found to not be installed anywhere in the fleet -- this is a standing observability gap, not an incident, but should be treated as high-priority infrastructure work given how much it limits every future slow-query investigation.
- A statement responsible for a large share of total_exec_time on the order-placement, balance-check, withdrawal, or settlement path -- escalate to performance/slow-queries with this workflow's output attached.
- pg_stat_statements.max eviction is suspected (a previously-seen statement is missing from the current view with no reset having occurred) -- escalate to raise the setting before more history is lost.

## Scripts That Should Not Be Run During Severe Incidents

- 04_configuring_log_min_duration_and_auto_explain.md -- Increases log volume and CloudWatch Logs ingestion cost proportional to the chosen threshold; auto_explain with log_analyze adds real per-statement overhead for statements that cross the threshold.
