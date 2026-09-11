# Scripts: Wait Event Analysis

Execution order, safety classification, and expected runtime for every script
in `observability/wait-event-analysis/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_current_wait_event_summary.sql` | Current backend counts by wait event type/name, with description. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_wait_event_contention_by_type_and_state.sql` | Wait event counts broken down by session state. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_per_session_wait_event_detail.sql` | Per-session wait event detail with description and query snippet. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_wait_event_type_reference.md` | Reference: wait_event_type meanings and whether each is normally actionable. | READ ONLY (reference documentation only; no SQL statements are executed by this file) | A few minutes to read. |

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

- Lock wait events dominate for more than a few minutes -- escalate immediately to concurrency-and-locking/lock-contention or blocked-queries; on wallet/ledger tables this risks a financial-operation-visible delay.
- IO wait events dominate with no corresponding CloudWatch storage-layer metric explanation -- escalate to performance/high-iops.
- A wait_event value not covered by the reference in script 04 appears prominently -- confirm its meaning against the current PostgreSQL 17 documentation before dismissing or escalating it, since new wait events are occasionally added between minor versions.

## Scripts That Should Not Be Run During Severe Incidents

- 04_wait_event_type_reference.md -- None -- this is reference/planning documentation, not an executable script. Any AWS-side action it describes (enabling a feature, creating an alarm) is called out explicitly and is a change-managed action outside this repository's SQL scope.
