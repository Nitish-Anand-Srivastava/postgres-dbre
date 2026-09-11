# Scripts: Minor Version Upgrade Readiness

Execution order, safety classification, and expected runtime for every script
in `maintenance/minor-version-upgrade-readiness/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_current_engine_version_inventory.sql` | Records the exact community and Aurora engine version this cluster is running, as the documented before-state for the upgrade. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_upgrade_blockers_precheck.sql` | Checks the three in-database conditions that most often block or complicate an engine upgrade: prepared transactions, replication slots, and long-running transactions. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_extension_and_settings_upgrade_surface.sql` | Inventories installed extensions and the operationally significant settings, so post-upgrade drift and extension updates can be identified against a recorded baseline. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_minor_version_upgrade_runbook.md` | AWS-side guidance for executing the minor version upgrade itself, including the blue/green alternative for minimizing the interruption. | INFORMATIONAL -- NO SQL EXECUTED, AWS CONSOLE/API GUIDANCE ONLY | Typically several minutes for an in-place cluster reboot; blue/green setup takes longer overall but shortens the actual interruption. |
| 05 | `05_post_upgrade_validation_runbook.md` | Guarded runbook for the database-side work an engine upgrade does not do for you: extension updates, planner statistics refresh, and post-upgrade validation. | LOW RISK WRITE (ANALYZE and ALTER EXTENSION ... UPDATE; SHARE UPDATE EXCLUSIVE locks only, no table rewrite -- see runbook before running any step) | Minutes, dominated by the ANALYZE of the largest hot tables. |

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

- A prepared transaction exists whose owning application/team cannot be identified before the window -- escalate rather than guessing, since rolling back a settlement or ledger two-phase transaction blindly can leave the exchange's books inconsistent with an external counterparty.
- The cluster is several minor versions behind and the accumulated change set can no longer be reviewed as a routine patch bump -- escalate for a scheduled, separately-tested upgrade rather than treating it as routine maintenance.

## Scripts That Should Not Be Run During Severe Incidents

- 04_minor_version_upgrade_runbook.md -- None from this file itself. The described in-place upgrade reboots every instance and terminates every connection; the blue/green switchover interrupts connections for a much shorter, bounded period.
- 05_post_upgrade_validation_runbook.md -- Real I/O and CPU for the duration of each ANALYZE; a brief lock on extension-owned objects during ALTER EXTENSION ... UPDATE; pg_stat_statements_reset() permanently discards accumulated query statistics.
