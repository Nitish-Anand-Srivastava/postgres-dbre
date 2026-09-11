# Scripts: Access Anomaly Investigation

Execution order, safety classification, and expected runtime for every script
in `security-and-access/access-anomaly-investigation/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_current_sessions_by_identity_and_origin.sql` | Captures the live session inventory -- role, client address, application, transport encryption, state, and age -- as the first evidence step of an access investigation. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_sessions_outside_expected_access_model.sql` | Classifies every live session against a configurable list of expected roles and an expected client network range, so sessions inconsistent with the documented access model sort to the top. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_privilege_escalation_surface.sql` | Enumerates the standing escalation surface -- elevated role attributes, re-grantable privileges, and objects reachable by every role via PUBLIC -- to answer what an implicated identity could have reached. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_access_anomaly_containment_runbook.md` | Guarded containment runbook: preserve evidence, block new connections for an implicated role, terminate its sessions, revoke over-broad grants, and hand off to the AWS-side investigation. | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) | Seconds per statement; the surrounding incident response, credential rotation, and AWS-side correlation run for as long as the incident does. |

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

- Any session is confirmed as an identity that is not part of the documented access model -- escalate to security incident response immediately; do not attempt to resolve it as a database-only issue.
- A role with access to wallet, ledger, deposit, or withdrawal tables is implicated -- escalate to security and compliance leadership the same hour, since customer-data-breach notification timelines may start at the point of detection.
- The escalation-surface query shows a privilege grant or role attribute that nobody can account for -- escalate rather than revoking it silently, because the grant itself is evidence of how the access was obtained.
- Containment would require terminating sessions belonging to a shared role that also serves production traffic -- escalate for a joint decision with the application owner; the availability impact of containment must be an explicit, recorded choice.

## Scripts That Should Not Be Run During Severe Incidents

- 04_access_anomaly_containment_runbook.md -- Step 1 blocks all new connections for the role, including legitimate ones. Step 2 aborts in-flight transactions for the terminated sessions. Step 3 changes access for every role covered by the revoked grant, not only the implicated one. Each step is disruptive by design and must be a recorded decision.
