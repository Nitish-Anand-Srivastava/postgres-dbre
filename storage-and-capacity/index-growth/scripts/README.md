# Scripts: Index Growth Investigation

Execution order, safety classification, and expected runtime for every script
in `storage-and-capacity/index-growth/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_largest_indexes.sql` | Top indexes by size. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_index_to_table_size_ratio.sql` | Index-to-heap size ratio per table. | READ ONLY | Low to moderate (a few seconds on a database with many partitions). |
| 03 | `03_index_usage_and_bloat.sql` | Index size, scan counters, and last-scan recency. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_unused_index_candidates.sql` | Never-scanned index drop candidates. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_duplicate_index_candidates.sql` | Structurally duplicate indexes. | READ ONLY | Low (sub-second to a few seconds) |
| 06 | `06_invalid_index_waste.sql` | INVALID indexes wasting storage. | READ ONLY | Low (sub-second to a few seconds) |

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

- A proposed drop target is an index on the live order-matching or wallet-balance path -- the owning team must sign off, because a wrong drop there is an immediate trading incident.
- Index bloat is severe enough that the REINDEX rebuild would meaningfully raise the Aurora volume high-water mark -- that is a cost decision, not a DBA decision.
- The same table keeps accumulating new indexes between audits -- escalate as a process problem to engineering leadership rather than repeatedly cleaning up after it.
- An index cannot be attributed to any query or team after investigation -- do not guess; escalate for ownership before dropping anything.

## Scripts That Should Not Be Run During Severe Incidents

_All scripts in this workflow are lightweight, read-only, and safe to run even during a severe incident. Prefer the narrower/most targeted script first if the system is under extreme load._
