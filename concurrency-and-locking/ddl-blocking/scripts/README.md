# Scripts: DDL Blocking Application Traffic

Execution order, safety classification, and expected runtime for every script
in `concurrency-and-locking/ddl-blocking/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_ddl_style_lock_waits.sql` | Identifies sessions holding or waiting for strong (DDL-style) lock modes and whether the DDL itself is granted or queued. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_who_is_queued_behind_ddl.sql` | Shows every other session now queued behind the DDL statement's own lock request. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_root_blocker_of_ddl.sql` | Identifies the original long-running transaction that the DDL statement itself is waiting on. | READ ONLY | Low (sub-second to a few seconds) |

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

- The DDL is part of an in-progress deployment and cannot be simply cancelled without breaking application compatibility -- escalate to the deploying team immediately to decide between waiting, cancelling, or rolling back the deployment.

## Scripts That Should Not Be Run During Severe Incidents

_All scripts in this workflow are lightweight, read-only, and safe to run even during a severe incident. Prefer the narrower/most targeted script first if the system is under extreme load._
