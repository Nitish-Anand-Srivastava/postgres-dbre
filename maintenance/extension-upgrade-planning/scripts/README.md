# Scripts: Extension Upgrade Planning

Execution order, safety classification, and expected runtime for every script
in `maintenance/extension-upgrade-planning/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_installed_extension_inventory.sql` | Baseline inventory of every extension currently installed and its active version, the starting point for upgrade planning. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_extension_version_skew_check.sql` | Compares each installed extension's active version against the newest version available on this Aurora engine release. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_extension_upgrade_runbook.md` | Guarded runbook for applying ALTER EXTENSION ... UPDATE for an extension identified as needing an upgrade by script 02. | LOW RISK WRITE (ALTER EXTENSION ... UPDATE; briefly locks the extension's owned objects, does not rewrite table data) | Seconds for the ALTER EXTENSION statement itself; allow additional time for pre-upgrade testing against a non-production copy for any major-version jump. |

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

- An installed extension is multiple major versions behind what is available, with no documented upgrade path tested -- escalate for a dedicated upgrade project rather than attempting it as routine maintenance.

## Scripts That Should Not Be Run During Severe Incidents

- 03_extension_upgrade_runbook.md -- Brief lock on objects owned by the extension during the upgrade; a major-version jump can change function signatures/output relied on by application code or other workflows.
