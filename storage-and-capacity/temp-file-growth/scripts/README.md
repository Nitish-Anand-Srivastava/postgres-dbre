# Scripts: Temporary File Growth Investigation

Execution order, safety classification, and expected runtime for every script
in `storage-and-capacity/temp-file-growth/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_temp_file_usage_by_database.sql` | Cumulative temp file usage per database. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_memory_and_temp_settings.sql` | Memory and temp file settings, plus per-role overrides. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_temp_heavy_statements.sql` | Top temp-file-generating statements. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_sessions_spilling_now.sql` | Active sessions, flagging live temp file spills. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_temp_files_on_disk.sql` | Temporary files currently on local disk. | READ ONLY | Low (sub-second to a few seconds) |
| 06 | `06_statistics_freshness.sql` | Planner statistics freshness per table. | READ ONLY | Low (sub-second to a few seconds) |

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

- `FreeLocalStorage` on any instance is approaching zero -- this is an availability risk and should be treated as an incident, with the offending workload stopped immediately.
- Queries are failing with temp file write errors on the writer, meaning the trading path is affected rather than only reporting.
- Temp file volume has grown sharply with no query change, no volume change, and no statistics drift -- involve application engineering to identify a changed access pattern.
- The correct fix requires a larger instance class or a new reporting architecture -- that is a cost and design decision for engineering leadership.

## Scripts That Should Not Be Run During Severe Incidents

_All scripts in this workflow are lightweight, read-only, and safe to run even during a severe incident. Prefer the narrower/most targeted script first if the system is under extreme load._
