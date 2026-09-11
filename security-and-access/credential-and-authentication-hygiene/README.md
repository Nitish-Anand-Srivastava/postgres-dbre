# Credential and Authentication Hygiene

**Category:** Security and Access | **Workflow:** `security-and-access/credential-and-authentication-hygiene`

## 1. Problem Description

Reviews how login roles actually authenticate and how long their credentials stay valid -- password expiry (`rolvaliduntil`), per-role connection limits, password hashing strength, IAM authentication coverage, and the connection-logging settings that make a credential compromise detectable after the fact.

## 2. Typical Symptoms

- A security review asks when each database credential was last rotated and what forces rotation if nobody remembers to do it.
- A service account's password is known to have been exposed (committed to a repository, pasted into a ticket, present in a container image) and the team needs to know exactly which roles are affected and how to rotate safely.
- Connections from a role that should have been decommissioned continue to succeed because its password never expired.

## 3. Business Impact

- A long-lived static database password with access to wallet, ledger, or order-book tables is the single highest-value credential on an exchange platform -- it grants direct data access with no application-layer authorization in front of it, and unlike an application API key it is rarely rotated on a schedule.
- Without `rolvaliduntil` set and without connection logging, a leaked credential remains valid indefinitely and its use is indistinguishable from legitimate traffic, which turns a containable incident into an unbounded one and makes the post-incident forensic question 'what did they access' unanswerable.

## 4. Possible Root Causes

- Roles were created with `CREATE ROLE ... LOGIN PASSWORD '...'` and no `VALID UNTIL` clause, so the credential never expires and rotation depends entirely on someone remembering.
- Application credentials live in a configuration file or secret store with no rotation automation, so rotation is a manual, coordinated, deploy-coupled task that gets deferred indefinitely.
- `log_connections`/`log_disconnections` are off (the Aurora default for both is off), so there is no record of which credential connected from where.
- Roles that could authenticate via IAM (short-lived tokens) were provisioned with passwords instead and never migrated.
- `rolconnlimit` is left at -1 (unlimited) for every role, so a compromised or misbehaving credential can consume the entire connection pool as well as read data.

## 5. Investigation Strategy

1. Inventory every login-capable role with its expiry date, connection limit, and whether it is IAM-enabled, ordered so never-expiring password roles surface first.
2. Check the cluster's authentication-relevant settings (password hashing algorithm, connection logging, SSL enforcement, session timeouts), all of which are parameter-group-managed on Aurora rather than editable in a configuration file.
3. Check per-role and per-database setting overrides, which can quietly weaken a cluster-wide default for exactly the role you are auditing.
4. Rotate or harden through the guarded runbook only after the full picture is known -- rotation without coordination disconnects the application.

## 6. Prerequisites

- Read access to pg_roles/pg_settings/pg_db_role_setting (available to any authenticated role). `pg_read_all_settings` membership gives visibility of settings whose values are otherwise restricted; note that password hashes themselves live in `pg_authid` and are deliberately not readable by non-superusers -- this workflow audits credential *policy*, not credential *material*.
- An inventory of which roles are human, which are service accounts, and which secret store holds each service account's password.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_login_roles_expiry_and_limits.sql`](scripts/01_login_roles_expiry_and_limits.sql) -- Inventories every login-capable role with its password expiry, connection limit, IAM-auth status, and elevated attributes, ordered so never-expiring password credentials surface first.
2. [`scripts/02_authentication_settings_and_role_overrides.sql`](scripts/02_authentication_settings_and_role_overrides.sql) -- Reports the cluster's authentication-relevant settings and every per-role/per-database setting override that could weaken them for a specific identity.
3. [`scripts/03_credential_rotation_and_hardening.md`](scripts/03_credential_rotation_and_hardening.md) -- Guarded runbook for rotating a database password without dropping application traffic, setting enforced expiry and connection limits, and hardening authentication settings on Aurora.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Aurora has no editable `pg_hba.conf`: which authentication methods are accepted, and from which networks, is decided by the DB cluster/instance parameter group (for example `rds.force_ssl`), the cluster's VPC security groups, and IAM authentication configuration -- so 'tighten pg_hba' is never the remediation on Aurora, and any runbook that says so was written for self-managed PostgreSQL.
- Aurora provides the built-in `rds_password` role: when password-command restriction is in effect on the cluster, roles need `rds_password` membership (or `rds_superuser`) to set or change passwords, including their own. A rotation that fails with a permissions error despite CREATEROLE is usually this, not a syntax problem.
- IAM database authentication issues short-lived tokens tied to an AWS identity, which is the cleanest way to eliminate a standing password for a service role; it is granted per role via `rds_iam` membership and requires a corresponding client-side change to request a token instead of reading a password from configuration.

## 8. Interpretation Guide

- `rolvaliduntil IS NULL` on a login-capable role means the password never expires. On a role with access to financial data this is the primary finding of this workflow, not a minor note.
- A `rolvaliduntil` already in the past on a role that is still connecting means the role is authenticating by some other means (IAM token, or a trust/peer-style path) -- the expiry did not lock it out, so investigate which mechanism is actually in use rather than assuming the credential is dead.
- `uses_iam_auth = true` means that role can present a short-lived AWS-issued token instead of a static password, which removes the long-lived-secret risk for that role; combined with `rolvaliduntil` in the past, it is a deliberately password-disabled, IAM-only role and is a good end state.
- `password_encryption = scram-sha-256` is the expected value; `md5` indicates a legacy configuration and any role whose password was set under it still has an md5 verifier stored until its password is re-set, even after the setting itself is changed.
- `rolconnlimit = -1` on a service role means one misbehaving or compromised client can exhaust `max_connections` for everyone; see connections/connection-exhaustion for what that looks like when it happens.
- Any row in the per-role settings result that sets a security-relevant parameter for a single role deserves a written justification -- a role-scoped override of a cluster-wide default is easy to set and very easy to forget.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If a specific credential is known to be exposed right now, the containment order is: set a new password first, then confirm the application has picked it up, then expire the old one -- and only disable login (`NOLOGIN`) immediately if the exposure is being actively exploited, accepting that this disconnects legitimate traffic on the same role.

**Short-term remediation** (hours to days):

- Set a `VALID UNTIL` date on every password-authenticated login role so rotation becomes enforced rather than remembered (guarded runbook, script 03).
- Set a realistic `rolconnlimit` per service role, sized from the application's pool configuration plus headroom, so no single credential can exhaust the cluster's connection budget.
- Enable `log_connections` (and `log_disconnections`) on the parameter group so credential use is attributable after the fact.

**Long-term engineering fix** (days to weeks):

- Migrate service roles from static passwords to IAM database authentication, prioritizing roles with access to wallet/ledger data, so the standing secret disappears entirely for those paths (see audit-logging-and-iam-auth).
- Automate rotation end to end via the secret store, with the dual-credential pattern described in the runbook, so a rotation never requires a coordinated human deploy.
- Add credential expiry and connection-limit checks to the scheduled security review so new roles cannot silently reintroduce a never-expiring password (see maintenance/routine-maintenance-checklist).

## 10. Production Safety

- Scripts 01 and 02 are read-only and safe at any time. They deliberately do not read `pg_authid`, so they never touch password verifier material.
- Script 03 is a guarded manual runbook. `ALTER ROLE ... PASSWORD` takes effect for *new* connections only -- existing sessions keep working until they reconnect, which is what makes the dual-credential rotation sequence safe, and also what makes an unannounced rotation look fine for hours and then fail at the next pool refresh.
- Never paste a real password into a ticket, a shared terminal recording, or an unencrypted runbook copy; the runbook shows the statement shape, and the actual secret should come from the secret store at execution time.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- A credential with access to wallet, ledger, or settlement tables is confirmed exposed -- escalate to security incident response immediately and in parallel with, not after, the rotation work.
- A login-capable role is found that no current team owns and whose password never expires -- escalate to the security team before dropping or disabling it, since an unowned but load-bearing credential can be behind an undocumented integration (see unused-and-orphaned-roles).
- `log_connections` is off on a cluster subject to an audit requirement for authentication records -- escalate to the platform team, since enabling it is a parameter-group change with lead time.

## 12. Related Issues

- [role-and-privilege-audit](../role-and-privilege-audit/README.md)
- [audit-logging-and-iam-auth](../audit-logging-and-iam-auth/README.md)
- [access-anomaly-investigation](../access-anomaly-investigation/README.md)
- [connection-exhaustion](../../connections/connection-exhaustion/README.md)
