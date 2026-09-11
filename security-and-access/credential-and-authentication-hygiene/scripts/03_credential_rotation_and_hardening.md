# 03_credential_rotation_and_hardening

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `03_credential_rotation_and_hardening.md` |
| Purpose | Guarded runbook for rotating a database password without dropping application traffic, setting enforced expiry and connection limits, and hardening authentication settings on Aurora. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance preferred; safe to run on a reader but results reflect only that reader's local activity |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | ALTER ROLE ... PASSWORD/VALID UNTIL/CONNECTION LIMIT are catalog-only and take effect for new connections; existing sessions are unaffected until they reconnect. NOLOGIN blocks all new connections for that role immediately. A parameter-group change affects the whole cluster. |
| Required privileges | CREATEROLE (or rds_superuser) to alter another role; on Aurora clusters with password-command restriction in effect, `rds_password` membership is additionally required to set any password. IAM permission to modify the DB cluster parameter group for the Aurora-side hardening steps. |
| Prerequisites | Scripts 01 and 02 completed; the client-side secret store location and its owning deploy process identified; the previous credential confirmed retrievable from secret-store version history before any in-place rotation. |
| Execution order | Step 03 of workflow `security-and-access/credential-and-authentication-hygiene` |
| Related scripts | 01_login_roles_expiry_and_limits.sql, 02_authentication_settings_and_role_overrides.sql |

## How to interpret / use this runbook

Choose Pattern A unless the role genuinely has no second identity available. In either pattern the verification step is the same: re-run script 01 and confirm the old credential's connection count reaches zero before expiring it.

---

## Before you run anything here

1. Complete scripts 01 and 02 so you know which roles are affected, whether the role authenticates by password or IAM token, and how many connections it currently holds.
2. Identify where the credential is stored on the client side (secret store entry, parameter store key, container environment variable) and who owns the deploy that picks up a change. A rotation the application cannot pick up is an outage, not a security improvement.
3. Never type a real password into a shared terminal or paste one into a ticket. Read it from the secret store at execution time, and prefer the psql `\password` meta-command (which prompts, hashes client-side, and keeps the plaintext out of the server log and your shell history) over an inline `PASSWORD '...'` literal.

## Pattern A -- dual-credential rotation (preferred, no downtime)

Rather than changing one role's password in place and racing the application to pick it up, alternate between two roles that hold identical group memberships:

1. Confirm both roles exist and are members of the same group role(s), so they have byte-for-byte identical privileges (verify with role-and-privilege-audit script 02 before relying on this).
2. Set a new password on the currently *inactive* role:

```sql
ALTER ROLE app_readwrite_b WITH PASSWORD 'read-from-secret-store-at-runtime' VALID UNTIL '2026-03-31';
```

3. Update the secret store and roll the application so it connects as the newly rotated role. Existing sessions on the old role keep working throughout -- `ALTER ROLE ... PASSWORD` only affects *new* connections.
4. Once `current_connections` for the old role reaches zero (re-run script 01), expire it:

```sql
ALTER ROLE app_readwrite_a VALID UNTIL '1970-01-01';
```

Rollback at any point before step 4: point the secret store back at the previous role, whose credential is still valid. That is the entire reason this pattern is preferred over in-place rotation.

## Pattern B -- in-place rotation (single role, brief risk window)

```sql
ALTER ROLE reporting_ro WITH PASSWORD 'read-from-secret-store-at-runtime' VALID UNTIL '2026-03-31';
```

Existing sessions survive; every *new* connection after this statement must use the new password. Update the secret store in the same change window, and expect authentication failures from any client whose pool refreshes before it picks up the new secret. Use this only for roles with a tolerant reconnect path -- never for the role serving order placement or settlement.

Rollback: re-run the same statement with the previous password (which requires that you still have it -- confirm it is retrievable from the secret store's version history *before* rotating, not after).

## Enforcing expiry on a role that never expires

```sql
ALTER ROLE reporting_ro VALID UNTIL '2026-03-31';
```

Set the date far enough out that the first enforced rotation is scheduled work, not a surprise, and put the date in the team's calendar the same day you set it. A `VALID UNTIL` that lapses unnoticed at 03:00 during Asian trading hours is a self-inflicted outage.

## Capping a service role's connection budget

```sql
ALTER ROLE app_readwrite CONNECTION LIMIT 120;
```

Size this from the application's configured pool maximum across all instances plus headroom for deploy overlap; setting it below the pool's steady-state size causes immediate connection failures. Rollback: `ALTER ROLE app_readwrite CONNECTION LIMIT -1;`.

## Disabling a compromised credential immediately

```sql
ALTER ROLE compromised_svc NOLOGIN;
```

This prevents new connections but does not terminate existing ones; session termination and the surrounding evidence-preservation sequence are covered in access-anomaly-investigation's containment runbook. Rollback: `ALTER ROLE compromised_svc LOGIN;`.

## Aurora-side hardening (parameter group, not SQL)

`password_encryption`, `log_connections`, `log_disconnections`, and `rds.force_ssl` are all set on the DB cluster parameter group -- `ALTER SYSTEM` is not available on Aurora:

```
aws rds modify-db-cluster-parameter-group \
  --db-cluster-parameter-group-name <cluster-parameter-group-name> \
  --parameters "ParameterName=log_connections,ParameterValue=1,ApplyMethod=immediate"
```

Confirm each parameter's apply type before assuming it is dynamic, and expect `log_connections` to add one log line per connection -- on a cluster with an aggressive connection churn pattern that is a meaningful log-volume increase, which is itself an argument for fixing the churn (see connections/connection-exhaustion).

## Do NOT

- Do NOT rotate a shared credential in place during peak trading hours; use the dual-credential pattern or wait for a low-volume window.
- Do NOT set `VALID UNTIL` to a near-term date on a role whose owner you have not spoken to -- an expiring credential fails closed, at the worst possible moment, with an authentication error that looks nothing like a scheduled change.
- Do NOT assume a rotation succeeded because the `ALTER ROLE` returned without error; confirm by watching the old role's `current_connections` drain to zero in script 01.
