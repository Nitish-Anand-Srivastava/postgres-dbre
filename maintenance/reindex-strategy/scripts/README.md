# Scripts: REINDEX CONCURRENTLY Campaign Planning

Execution order, safety classification, and expected runtime for every script
in `maintenance/reindex-strategy/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_reindex_candidate_ranking.sql` | Ranks indexes by size and usage to sequence the campaign, reusing the same bloat/usage view as the routine checklist. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_reindex_progress_monitor.sql` | Monitors live progress of any REINDEX CONCURRENTLY (or CREATE INDEX CONCURRENTLY) currently running, to confirm each batch is progressing before starting the next. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_reindex_concurrently_runbook.md` | Guarded runbook for executing a batched REINDEX CONCURRENTLY campaign across the candidates identified in script 01. | LOW RISK WRITE (REINDEX CONCURRENTLY takes SHARE UPDATE EXCLUSIVE, not ACCESS EXCLUSIVE; ordinary reads/writes continue -- see runbook for lock/disk-space details) | Minutes to hours per index depending on size; plan the full campaign across multiple maintenance windows for a large backlog. |

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

- Available disk headroom on the cluster is not comfortably larger than the single largest candidate index's current size -- escalate for a capacity check (storage-and-capacity/capacity-forecasting) before starting the campaign, since REINDEX CONCURRENTLY needs to build the full new index before dropping the old one.

## Scripts That Should Not Be Run During Severe Incidents

- 03_reindex_concurrently_runbook.md -- Real I/O/CPU load for the duration of each index rebuild, plus roughly double that index's disk space temporarily; blocks other DDL and VACUUM on the same table until each REINDEX CONCURRENTLY completes.
