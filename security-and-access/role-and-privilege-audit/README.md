# Role and Privilege Audit

**Category:** Security and Access | **Workflow:** `security-and-access/role-and-privilege-audit`

## 1. Problem Description

A routine or pre-audit inventory of every role in the cluster, its memberships, and the object-level grants it holds -- the standing baseline question 'who can do what' that access reviews, compliance audits, and incident post-mortems all eventually need answered.

## 2. Typical Symptoms

- No active symptom -- typically run ahead of a compliance/security review, an access-control audit, or as part of onboarding/offboarding verification.
- Also run reactively after a suspected privilege-escalation or unauthorized-access incident to establish exactly what the implicated role could actually do.

## 3. Business Impact

- On a financial trading platform, an unreviewed or overly broad privilege grant is a direct regulatory and security exposure -- auditors and incident responders need a fast, authoritative answer to 'what could this role touch', not a manual crawl through migration history.

## 4. Possible Root Causes

- Privileges accumulate over time as roles are granted broader access for a one-off task and never revoked afterward.
- Group/role membership grants (GRANT role TO role) are harder to audit visually than direct object grants and are easy to lose track of.
- A role created for a specific service inherits far more than it needs because it was cloned from an existing, already-over-privileged role.

## 5. Investigation Strategy

1. Confirm what the currently connected auditing role itself can do (its own super/create/replication attributes and memberships), so findings are interpreted with the right context.
2. Enumerate every role in the cluster and its full membership graph.
3. Enumerate explicit object-level grants (tables, views, materialized views) across all non-system schemas to find grants that bypass role membership entirely.

## 6. Prerequisites

- A role with SELECT access to pg_roles/pg_auth_members/pg_class (any authenticated role can read these catalogs; no elevated privilege is required for read-only auditing).

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_current_role_capabilities.sql`](scripts/01_current_role_capabilities.sql) -- Confirms what the currently connected auditing role itself can do -- its super/create/replication attributes and its own group memberships -- as context for interpreting the rest of the audit.
2. [`scripts/02_all_roles_and_memberships.sql`](scripts/02_all_roles_and_memberships.sql) -- Enumerates every non-system role in the cluster along with its login/create/replication attributes and its full group-membership list.
3. [`scripts/03_object_level_grants_by_schema.sql`](scripts/03_object_level_grants_by_schema.sql) -- Enumerates explicit, individually-granted table/view/materialized-view privileges across all non-system schemas, the grants that bypass group-role membership entirely.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Aurora/RDS does not expose a true PostgreSQL superuser; the bootstrap application role is a member of rds_superuser instead, which is intentionally weaker (no filesystem or OS-level access) -- rolsuper should read false for every role you find, and a true value is itself an anomaly worth investigating rather than an expected top-of-hierarchy role.

## 8. Interpretation Guide

- A role with rolsuper = true should not exist on Aurora at all under normal operation -- the platform enforces this via rds_superuser instead, so an unexpected true here is worth escalating immediately.
- A large member_of_roles array is not inherently wrong (role-based access control is the intended pattern) but every membership should be traceable to a documented reason; an undocumented membership discovered here is the actual finding, not the membership itself.
- Explicit object-level grants that duplicate what a role already receives via group membership are redundant and make future revocation error-prone -- consolidate onto the group role instead.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If an active incident implicates a specific role, use this audit's output to determine the exact blast radius (every object it can reach) before deciding on containment (e.g., REVOKE or a temporary role disable via NOLOGIN).

**Short-term remediation** (hours to days):

- Revoke any explicit object-level grant that duplicates an existing group-role membership, consolidating access onto the group.
- Document the business justification for every non-obvious role membership found.

**Long-term engineering fix** (days to weeks):

- Adopt a standing quarterly role-and-privilege-audit cadence (see maintenance/routine-maintenance-checklist) rather than only auditing reactively after an incident or ahead of a compliance deadline.
- Move toward a small number of well-documented group roles (e.g. app_readonly, app_readwrite, reporting) with individual login roles granted membership only in those groups, instead of ad hoc direct grants.

## 10. Production Safety

- Every script in this workflow is a read-only catalog query; nothing here modifies a role or a grant.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Any role with rolsuper = true, or an unexplained rolbypassrls = true, is found -- escalate to the security team immediately regardless of audit cadence.
- A role is found with object-level access it has no documented business justification for -- escalate to the role's owning team before revoking, in case the access is load-bearing for an undocumented integration.

## 12. Related Issues

- [unused-and-orphaned-roles](../unused-and-orphaned-roles/README.md)
- [public-schema-exposure](../public-schema-exposure/README.md)
- [audit-logging-and-iam-auth](../audit-logging-and-iam-auth/README.md)
- [row-level-security-review](../row-level-security-review/README.md)
- [access-anomaly-investigation](../access-anomaly-investigation/README.md)
