# Scripts: Runaway Query

Execution order, safety classification, and expected runtime for every script
in `incident-response/runaway-query/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_runaway_candidates.sql` | Active queries above the runtime threshold, ranked by runtime. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_target_backend_detail.sql` | Full detail for one backend: query text, ages, wait state, blocking relationships. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_collateral_damage.sql` | Sessions blocked behind the runaway, plus temp-file volume per database. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_statement_history.sql` | Statement history for temp-file and IO-heavy statements. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_stop_the_runaway_query.md` | Guarded actions: cancel the runaway, handle the open-transaction case, terminate if justified. | ELEVATED RISK -- MANUAL EXECUTION ONLY, CANCELS A STATEMENT OR ROLLS BACK THE TARGET TRANSACTION (read every warning in this file first) | Seconds to signal; rollback of a large write transaction can take considerably longer. |

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

- The runaway is a settlement, reconciliation or withdrawal-processing statement -- escalate to treasury and compliance before stopping it, because a partially applied financial batch is worse than a slow one.
- The backend is not a client backend -- escalate to database engineering and do not signal it.
- Cancel and terminate both fail to stop it, which points at a stuck backend and warrants an AWS support case.
- The same runaway shape recurs after remediation, which means the fix is upstream in the application or in analyst tooling rather than in this incident.

## Scripts That Should Not Be Run During Severe Incidents

- 05_stop_the_runaway_query.md -- A cancel aborts the running statement and leaves the connection and any open transaction alive. A terminate ends the connection and rolls the whole transaction back.
