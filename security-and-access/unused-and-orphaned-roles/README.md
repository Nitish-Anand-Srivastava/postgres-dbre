# Unused and Orphaned Roles

**Category:** Security and Access | **Workflow:** `security-and-access/unused-and-orphaned-roles`

## 1. Problem Description

Roles that exist in the cluster but show no evidence of ongoing legitimate use -- no active or recent connections, no owned objects, and no group-membership purpose -- and are therefore candidates for cleanup, distinct from role-and-privilege-audit's broader 'what can everyone do' inventory.

## 2. Typical Symptoms

- A role-and-privilege-audit turns up roles nobody on the current team recognizes.
- An employee/service offboarding checklist requires confirming a specific role is no longer in use before dropping it.

## 3. Business Impact

- Every unused login-capable role is standing attack surface -- a credential that, if ever compromised, still works, even though no legitimate process uses it -- and every unused role also adds noise that makes the next audit slower and less reliable.

## 4. Possible Root Causes

- A role created for a former employee, a decommissioned service, or a one-off migration/analysis task was never dropped afterward.
- A role still owns objects (so DROP ROLE fails outright) even though nothing connects as that role anymore, because ownership was never reassigned when the role's active use ended.

## 5. Investigation Strategy

1. For every non-system role, check current connections, historical objects owned, and whether it is used purely as a group (has members) or an actual login identity.
2. Cross-reference candidates against your organization's service/employee inventory before taking any action -- absence of a *current* connection does not prove a role is unused if it connects rarely (e.g. a monthly batch job).

## 6. Prerequisites

- Read access to pg_roles/pg_stat_activity/pg_class (standard for any authenticated role); an inventory of expected services/employees to cross-reference candidates against.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_candidate_roles_by_activity_and_ownership.sql`](scripts/01_candidate_roles_by_activity_and_ownership.sql) -- Ranks every non-system role by current connection count, objects owned, and group-membership purpose, surfacing the roles with the least evidence of ongoing legitimate use first.
2. [`scripts/02_role_cleanup_runbook.md`](scripts/02_role_cleanup_runbook.md) -- Guarded, manual runbook for reassigning ownership away from and then dropping a role confirmed abandoned by script 01 and by cross-referencing your service/employee inventory.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Do not include the built-in rds_* roles (rds_superuser, rds_replication, rds_password, rds_iam, and similar) in any cleanup consideration -- these are managed by the Aurora/RDS control plane and are expected to exist regardless of whether they currently have members.

## 8. Interpretation Guide

- A role with objects_owned = 0, current_connections = 0, and has_members_count = 0 is a strong cleanup candidate, but 'strong candidate' is not 'confirmed safe to drop' -- pg_stat_activity only shows connections that exist right now, not a historical connection log, so a role used only for an infrequent scheduled job can look identical to a truly abandoned one on a single snapshot.
- is_rds_builtin_role = true rows (the rds_* family) are AWS-managed infrastructure roles, not candidates for cleanup regardless of how the other columns look.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- None -- this is never an emergency workflow; act deliberately, not urgently, when removing access.

**Short-term remediation** (hours to days):

- For a confirmed-abandoned role that still owns objects, reassign ownership (REASSIGN OWNED BY ... TO ...) to an appropriate current role before dropping it, then DROP OWNED BY ... to clear any remaining grants, then DROP ROLE.

**Long-term engineering fix** (days to weeks):

- Add role deactivation (REVOKE the ability to log in via ALTER ROLE ... NOLOGIN, observed for a cooldown period) as a standard step in the employee/service offboarding checklist, ahead of an eventual DROP ROLE, so cleanup does not depend on someone remembering to run this audit.

## 10. Production Safety

- The investigation query (script 01) is read-only. The cleanup runbook (script 02) is a guarded, manual template -- REASSIGN OWNED / DROP OWNED / DROP ROLE are irreversible with respect to the dropped role's identity and must never be run against a candidate that has not been independently confirmed abandoned.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- A candidate role turns out to still be referenced by application connection-string configuration or infrastructure-as-code even though it shows zero current connections -- treat this as a near-miss and escalate to the owning team before it is actually dropped.

## 12. Related Issues

- [role-and-privilege-audit](../role-and-privilege-audit/README.md)
- [routine-maintenance-checklist](../../maintenance/routine-maintenance-checklist/README.md)
