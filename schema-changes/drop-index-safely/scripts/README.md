# Scripts: Dropping an Index Safely

Execution order, safety classification, and expected runtime for every script
in `schema-changes/drop-index-safely/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_unused_index_candidates.sql` | Never-scanned index drop candidates. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_duplicate_index_candidates.sql` | Structurally duplicate indexes. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_index_role_and_drop_verdict.sql` | Structural role and explicit drop verdict per index. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_drop_index_safely_runbook.md` | Guarded DDL runbook: rehearsing and executing an index drop. | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) | Seconds for the rehearsal; seconds to minutes for the concurrent drop. |
| 05 | `05_post_drop_regression_check.sql` | Post-drop query regression check. | READ ONLY | Low (sub-second to a few seconds) |

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

- The candidate is on the live order-matching or wallet-balance path -- the owning team must sign off, because a wrong drop there is an immediate trading incident.
- The index cannot be attributed to any query or team after investigation -- do not guess; escalate for ownership rather than dropping something nobody understands.
- The index is the table's replica identity or supports an active logical replication or DMS pipeline.
- A query regression is observed after a drop and recreating the index does not resolve it -- escalate, because something else changed at the same time.

## Scripts That Should Not Be Run During Severe Incidents

- 04_drop_index_safely_runbook.md -- Varies by step -- read each step's own warning before executing it.
