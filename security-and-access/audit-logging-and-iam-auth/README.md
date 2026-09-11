# Audit Logging (pgaudit) and IAM Database Authentication

**Category:** Security and Access | **Workflow:** `security-and-access/audit-logging-and-iam-auth`

## 1. Problem Description

Reviews two related but distinct access-security controls: whether the pgaudit extension is installed and configured for detailed session/object audit logging, and whether IAM database authentication (via the built-in rds_iam role) is in use as an alternative to password authentication.

## 2. Typical Symptoms

- A compliance review asks for evidence of detailed audit logging of who accessed/modified specific data.
- A security review asks whether database credentials are password-based (a standing secret to rotate/leak) or IAM-token-based (short-lived, tied to an AWS identity).

## 3. Business Impact

- For a regulated trading platform, an auditable trail of who read or modified specific rows/tables is frequently a direct compliance requirement, not just a best practice; similarly, IAM authentication removes a class of long-lived-password-leak risk that password authentication cannot eliminate on its own.

## 4. Possible Root Causes

- pgaudit was never installed because it must be explicitly requested (a shared_preload_libraries + CREATE EXTENSION change), unlike PostgreSQL's own baseline statement logging.
- Application roles were provisioned with password authentication from the start and nobody has since migrated them to IAM authentication.
- pgaudit is installed but its scope (pgaudit.log) is set too broadly or too narrowly for the actual compliance requirement -- discovered only when someone asks for a specific audit trail and it is not there.

## 5. Investigation Strategy

1. Check whether pgaudit is installed and, if so, what its current logging scope is configured to.
2. Check which roles are currently members of the built-in rds_iam role, which is how IAM database authentication is granted per role on Aurora.

## 6. Prerequisites

- pg_monitor role membership; read access to pg_extension/pg_settings/pg_auth_members (standard for any authenticated role).

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_pgaudit_installation_and_scope.sql`](scripts/01_pgaudit_installation_and_scope.sql) -- Checks whether the pgaudit extension is installed and, if so, reports its current logging-scope configuration.
2. [`scripts/02_iam_authenticated_roles.sql`](scripts/02_iam_authenticated_roles.sql) -- Lists every role currently granted IAM database authentication via membership in the built-in rds_iam role.
3. [`scripts/03_installing_pgaudit_and_granting_iam_auth.md`](scripts/03_installing_pgaudit_and_granting_iam_auth.md) -- Guarded runbook for installing pgaudit (change-managed, reboot-driving) and for granting IAM database authentication to a role.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- IAM database authentication on Aurora PostgreSQL is granted per role by making that role a member of the built-in rds_iam role -- it does not exist as a concept on self-managed PostgreSQL at all, which instead would rely on an external authentication mechanism (LDAP/Kerberos) configured very differently.

## 8. Interpretation Guide

- pgaudit_installed = false means no extension-level audit trail exists beyond whatever PostgreSQL's own log_statement/log_min_duration_statement settings capture (which log the statement, but not necessarily in the structured, object-level form pgaudit provides) -- confirm whether this actually satisfies your compliance requirement before assuming logging is 'good enough'.
- A role appearing in the IAM-authenticated members list can connect using a short-lived IAM auth token instead of a static password; a role that legitimately should be using IAM authentication but does not appear here is still relying on a long-lived password credential.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- None -- this is a review workflow, not an active-incident one.

**Short-term remediation** (hours to days):

- For any role that should be using IAM authentication and is not yet, grant it rds_iam membership and update the connecting application/service to request an IAM auth token instead of a static password (see this workflow's runbook).

**Long-term engineering fix** (days to weeks):

- If pgaudit is not installed and a compliance requirement genuinely needs object-level audit logging, plan its installation and shared_preload_libraries change as a change-managed maintenance-window activity (see this workflow's runbook and maintenance/parameter-group-change-management, since shared_preload_libraries changes require a reboot).
- Migrate remaining password-authenticated application roles to IAM authentication over time as a standing security posture improvement, prioritizing roles with access to the most sensitive data first.

## 10. Production Safety

- The investigation scripts here are read-only. Installing pgaudit (CREATE EXTENSION plus a shared_preload_libraries parameter-group change) and granting rds_iam membership are both guarded, change-managed steps documented in this workflow's runbook -- neither is executed automatically by any script here.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- A compliance deadline requires object-level audit evidence and pgaudit is confirmed not installed -- escalate to the platform/compliance team immediately, since installing it requires a reboot-driven maintenance window that needs lead time to schedule.

## 12. Related Issues

- [role-and-privilege-audit](../role-and-privilege-audit/README.md)
- [ssl-and-connection-security](../ssl-and-connection-security/README.md)
