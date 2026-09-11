# Security and Access

**Category:** `security-and-access`

This is the index for the `security-and-access/` category: every workflow
(issue directory) below addresses a distinct, real operational problem or
DBA use case for this Aurora PostgreSQL toolkit, per the repository's
one-parent-directory-per-problem design. Each workflow directory is
self-contained -- its own `README.md` (problem description, symptoms,
business impact, root causes, investigation strategy, prerequisites,
interpretation guide, remediation options, production safety, and
escalation criteria) and a `scripts/` directory of numbered, read-only-by
-default investigation scripts (see each workflow's `scripts/README.md`
for the full script-by-script execution table).

## Workflows

| Workflow | Summary |
| --- | --- |
| [`role-and-privilege-audit`](role-and-privilege-audit/README.md) | A routine or pre-audit inventory of every role in the cluster, its memberships, and the object-level grants it holds -- the standing baseline question 'who can do what' that access reviews, compliance audits, and incident post-mortems all eventually need answered. |
| [`unused-and-orphaned-roles`](unused-and-orphaned-roles/README.md) | Roles that exist in the cluster but show no evidence of ongoing legitimate use -- no active or recent connections, no owned objects, and no group-membership purpose -- and are therefore candidates for cleanup, distinct from role-and-privilege-audit's broader 'what can everyone do' inventory. |
| [`public-schema-exposure`](public-schema-exposure/README.md) | Reviews exactly what the `public` schema and its objects actually grant to the PUBLIC pseudo-role on this specific database, since PostgreSQL 15 changed the shipped defaults and it is unsafe to assume either the old or the new behavior without verifying. |
| [`ssl-and-connection-security`](ssl-and-connection-security/README.md) | Verifies whether client connections to the cluster are actually using SSL/TLS, and whether SSL enforcement is configured at the Aurora parameter-group level -- distinct from a typical PostgreSQL deployment, where SSL enforcement is a postgresql.conf/pg_hba.conf concern rather than a parameter-group one. |
| [`audit-logging-and-iam-auth`](audit-logging-and-iam-auth/README.md) | Reviews two related but distinct access-security controls: whether the pgaudit extension is installed and configured for detailed session/object audit logging, and whether IAM database authentication (via the built-in rds_iam role) is in use as an alternative to password authentication. |
| [`row-level-security-review`](row-level-security-review/README.md) | Reviews which tables actually have row-level security (RLS) enabled, what their policies allow, and which roles can bypass RLS entirely -- the control that decides whether a single compromised or over-broad application role can read every customer's wallet balance and ledger history, or only the rows it is entitled to. |
| [`credential-and-authentication-hygiene`](credential-and-authentication-hygiene/README.md) | Reviews how login roles actually authenticate and how long their credentials stay valid -- password expiry (`rolvaliduntil`), per-role connection limits, password hashing strength, IAM authentication coverage, and the connection-logging settings that make a credential compromise detectable after the fact. |
| [`access-anomaly-investigation`](access-anomaly-investigation/README.md) | The reactive workflow for 'someone or something is connecting to this database that should not be' -- establishing, from catalog and live-activity data alone, who is currently connected, from where, over what transport, with what privileges, and which of those facts is inconsistent with the documented access model. |

## Related Categories

- [`connections/connection-exhaustion`](../../connections/connection-exhaustion/README.md)
- [`maintenance/parameter-group-change-management`](../../maintenance/parameter-group-change-management/README.md)
- [`maintenance/routine-maintenance-checklist`](../../maintenance/routine-maintenance-checklist/README.md)

Start with the workflow whose title most closely matches the symptom you are
investigating; if uncertain, `database-health/comprehensive-health-check`
and `incident-response/production-triage` both provide a broad first pass
that surfaces which specific workflow to open next.
