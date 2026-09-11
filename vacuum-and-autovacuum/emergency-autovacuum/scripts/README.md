# Scripts: Emergency / Anti-Wraparound Autovacuum

Execution order, safety classification, and expected runtime for every script
in `vacuum-and-autovacuum/emergency-autovacuum/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_confirm_emergency_vacuum.sql` | Confirms whether a currently running vacuum is in anti-wraparound/failsafe mode by cross-referencing its target table's age against the configured thresholds. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_safe_handling_during_emergency_vacuum.md` | Manual guidance for what to do (and not do) while an anti-wraparound/failsafe vacuum is in progress. | DOCUMENTATION -- no SQL executed by this file itself | Variable -- depends on table size and chosen batch size; see runbook. |

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

- The database has already begun refusing new transactions (full wraparound outage) -- this is beyond routine emergency-autovacuum monitoring; escalate as a major incident immediately.

## Scripts That Should Not Be Run During Severe Incidents

- 02_safe_handling_during_emergency_vacuum.md -- None from this file directly.
