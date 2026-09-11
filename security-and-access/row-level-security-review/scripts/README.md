# Scripts: Row-Level Security Coverage Review

Execution order, safety classification, and expected runtime for every script
in `security-and-access/row-level-security-review/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_rls_status_by_table.sql` | Inventories every table in a non-system schema with its row-level-security flags, policy count, owner, and size, so sensitive tables with no coverage surface first. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_policy_definitions_and_bypass_roles.sql` | Prints the actual USING/WITH CHECK expression of every policy in the database, then lists every role that bypasses RLS entirely. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_rls_coverage_for_sensitive_table.sql` | End-to-end RLS review of one specific high-sensitivity table -- flags, policies, and object-level grants -- defaulting to public.wallets and guarded so it prints a notice rather than failing if that table does not exist. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_enabling_row_level_security.md` | Guarded runbook for enabling RLS, adding a tenant-isolation policy, forcing it for the table owner, and removing a BYPASSRLS attribute -- with lock behavior and rollback for each step. | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) | Milliseconds per statement once the lock is acquired; the surrounding verification and rollout is a change-managed exercise. |

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

- A table holding customer balances, ledger entries, or withdrawal records is found with RLS disabled and no compensating documented control -- escalate to the security/compliance owner the same day.
- A login-capable application or human role is found with `rolbypassrls = true` and no documented justification -- escalate immediately; this is a complete exemption from the isolation model, not a tuning detail.
- Policy definitions found in the database do not match the isolation model the compliance documentation claims is in place -- escalate before changing anything, since the documentation may be describing an intended design that was never implemented.

## Scripts That Should Not Be Run During Severe Incidents

- 04_enabling_row_level_security.md -- Each statement takes a brief ACCESS EXCLUSIVE lock (milliseconds of catalog work, but it queues behind and then blocks concurrent access on the table). Once enabled, every query against the table returns a restricted row set -- an incorrect policy presents to the application as missing data.
