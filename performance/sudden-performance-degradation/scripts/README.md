# Scripts: Sudden Performance Degradation

Execution order, safety classification, and expected runtime for every script
in `performance/sudden-performance-degradation/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_snapshot_current_state.sql` | Captures a broad current-state snapshot (sessions, states, wait events) as the first forensic step. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_dominant_blocking_chain.sql` | Identifies the single most impactful blocking session, if one exists, to prioritize the fastest possible fix. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_recovery_role_check.sql` | Confirms whether this instance is currently the writer or a reader, to detect an unnoticed failover. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_autovacuum_emergency_check.sql` | Checks for an anti-wraparound or failsafe autovacuum currently running, which can consume significant resources and cannot be safely cancelled. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_recent_wal_and_checkpoint_spike.sql` | Checks for a recent spike in WAL generation or forced checkpoints that could correlate with the incident window. | READ ONLY | Low (sub-second to a few seconds) |

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

- No root cause identified within 10-15 minutes of investigation -- escalate to database engineering leadership and open the full incident-response/production-triage checklist in parallel.

## Scripts That Should Not Be Run During Severe Incidents

_All scripts in this workflow are lightweight, read-only, and safe to run even during a severe incident. Prefer the narrower/most targeted script first if the system is under extreme load._
