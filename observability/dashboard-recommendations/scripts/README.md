# Scripts: Baseline Aurora PostgreSQL DBA Dashboard Recommendations

Execution order, safety classification, and expected runtime for every script
in `observability/dashboard-recommendations/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_single_row_dashboard_snapshot.sql` | Single-row cluster-at-a-glance snapshot for a quick-start dashboard panel. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_baseline_dashboard_layout_recommendations.md` | Reference: recommended baseline dashboard panel layout, grouped by operational question. | INFORMATIONAL -- NO SQL EXECUTED, DASHBOARD/ALERTING DESIGN GUIDANCE ONLY | An implementation planning exercise; not a runtime-bound script. |

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

- This workflow does not define escalation criteria of its own -- each panel group's escalation threshold is inherited from the workflow that owns that signal (see Related Issues and each panel's source workflow).

## Scripts That Should Not Be Run During Severe Incidents

- 02_baseline_dashboard_layout_recommendations.md -- None -- this is reference/planning documentation, not an executable script. Any AWS-side action it describes (enabling a feature, creating an alarm) is called out explicitly and is a change-managed action outside this repository's SQL scope.
