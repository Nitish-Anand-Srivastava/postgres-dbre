# Scripts: Credential and Authentication Hygiene

Execution order, safety classification, and expected runtime for every script
in `security-and-access/credential-and-authentication-hygiene/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_login_roles_expiry_and_limits.sql` | Inventories every login-capable role with its password expiry, connection limit, IAM-auth status, and elevated attributes, ordered so never-expiring password credentials surface first. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_authentication_settings_and_role_overrides.sql` | Reports the cluster's authentication-relevant settings and every per-role/per-database setting override that could weaken them for a specific identity. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_credential_rotation_and_hardening.md` | Guarded runbook for rotating a database password without dropping application traffic, setting enforced expiry and connection limits, and hardening authentication settings on Aurora. | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) | Milliseconds per statement; the coordinated rollout (secret store update, application restart, draining the old role's connections) is the part that takes a change window. |

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

- A credential with access to wallet, ledger, or settlement tables is confirmed exposed -- escalate to security incident response immediately and in parallel with, not after, the rotation work.
- A login-capable role is found that no current team owns and whose password never expires -- escalate to the security team before dropping or disabling it, since an unowned but load-bearing credential can be behind an undocumented integration (see unused-and-orphaned-roles).
- `log_connections` is off on a cluster subject to an audit requirement for authentication records -- escalate to the platform team, since enabling it is a parameter-group change with lead time.

## Scripts That Should Not Be Run During Severe Incidents

- 03_credential_rotation_and_hardening.md -- ALTER ROLE ... PASSWORD/VALID UNTIL/CONNECTION LIMIT are catalog-only and take effect for new connections; existing sessions are unaffected until they reconnect. NOLOGIN blocks all new connections for that role immediately. A parameter-group change affects the whole cluster.
