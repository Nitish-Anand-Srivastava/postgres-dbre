# Scripts: High IOPS / Storage I/O Saturation

Execution order, safety classification, and expected runtime for every script
in `performance/high-iops/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_database_cache_hit_ratio.sql` | Computes the buffer cache hit ratio per database as a proxy for how much read traffic is reaching storage. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_top_io_generating_queries.sql` | Identifies statements generating the most shared buffer reads, the strongest query-level proxy for storage I/O. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_io_by_backend_type.sql` | Breaks down I/O by backend type (client backend, autovacuum, checkpointer, etc.) using pg_stat_io. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_checkpoint_frequency.sql` | Checks checkpoint frequency and the ratio of forced vs. scheduled checkpoints, a major source of write I/O. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_temp_file_io.sql` | Checks temp file generation, which directly consumes read/write IOPS for spilled sorts/hashes. | READ ONLY | Low (sub-second to a few seconds) |

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

- IOPS sustained near the storage subsystem's practical ceiling for the instance class with no single fixable query -- this is a capacity/billing decision, escalate to database engineering leadership.
- Suspected Aurora storage-layer issue (not explained by any workload change) -- open an AWS Support case.

## Scripts That Should Not Be Run During Severe Incidents

_All scripts in this workflow are lightweight, read-only, and safe to run even during a severe incident. Prefer the narrower/most targeted script first if the system is under extreme load._
