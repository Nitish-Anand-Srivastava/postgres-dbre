"""Workflow definitions: security-and-access/ category (8 workflow directories).

This is an OPEN_CATALOG category (see tools/validation/catalog.py) -- there is
no fixed, exact required workflow slug list, only a requirement that the
category directory exists and has at least one workflow. The eight workflows
below cover role/privilege auditing, orphaned-role cleanup, the public-schema
default-privilege posture, SSL/TLS enforcement, audit-logging/IAM-auth review,
row-level-security coverage on sensitive wallet/ledger tables, credential and
authentication hygiene, and reactive access-anomaly investigation -- together
a reasonably comprehensive answer to the day-to-day access-control questions a
DBA is asked on an Aurora PostgreSQL cluster backing a regulated trading
platform.
"""
from __future__ import annotations

from typing import List

from . import sql_blocks as sb
from .helpers import (
    ANY_INSTANCE,
    PG_MONITOR,
    TABLE_OWNER_OR_DDL,
    WRITER_PREFERRED,
    md_script,
    sql_script,
)
from .model import Workflow

CATEGORY_SLUG = "security-and-access"
CATEGORY_TITLE = "Security and Access"


def _wf(**kwargs) -> Workflow:
    kwargs.setdefault("category_slug", CATEGORY_SLUG)
    kwargs.setdefault("category_title", CATEGORY_TITLE)
    return Workflow(**kwargs)


WORKFLOWS: List[Workflow] = []

# ---------------------------------------------------------------------------
# role-and-privilege-audit
# ---------------------------------------------------------------------------
WORKFLOWS.append(_wf(
    slug="role-and-privilege-audit",
    title="Role and Privilege Audit",
    summary="A routine or pre-audit inventory of every role in the cluster, its memberships, and the object-level grants it holds -- the standing baseline question 'who can do what' that access reviews, compliance audits, and incident post-mortems all eventually need answered.",
    symptoms=["No active symptom -- typically run ahead of a compliance/security review, an access-control audit, or as part of onboarding/offboarding verification.", "Also run reactively after a suspected privilege-escalation or unauthorized-access incident to establish exactly what the implicated role could actually do."],
    business_impact=["On a financial trading platform, an unreviewed or overly broad privilege grant is a direct regulatory and security exposure -- auditors and incident responders need a fast, authoritative answer to 'what could this role touch', not a manual crawl through migration history."],
    root_causes=["Privileges accumulate over time as roles are granted broader access for a one-off task and never revoked afterward.", "Group/role membership grants (GRANT role TO role) are harder to audit visually than direct object grants and are easy to lose track of.", "A role created for a specific service inherits far more than it needs because it was cloned from an existing, already-over-privileged role."],
    investigation_strategy=["Confirm what the currently connected auditing role itself can do (its own super/create/replication attributes and memberships), so findings are interpreted with the right context.", "Enumerate every role in the cluster and its full membership graph.", "Enumerate explicit object-level grants (tables, views, materialized views) across all non-system schemas to find grants that bypass role membership entirely."],
    prerequisites=["A role with SELECT access to pg_roles/pg_auth_members/pg_class (any authenticated role can read these catalogs; no elevated privilege is required for read-only auditing)."],
    interpretation_guide=["A role with rolsuper = true should not exist on Aurora at all under normal operation -- the platform enforces this via rds_superuser instead, so an unexpected true here is worth escalating immediately.", "A large member_of_roles array is not inherently wrong (role-based access control is the intended pattern) but every membership should be traceable to a documented reason; an undocumented membership discovered here is the actual finding, not the membership itself.", "Explicit object-level grants that duplicate what a role already receives via group membership are redundant and make future revocation error-prone -- consolidate onto the group role instead."],
    remediation_immediate=["If an active incident implicates a specific role, use this audit's output to determine the exact blast radius (every object it can reach) before deciding on containment (e.g., REVOKE or a temporary role disable via NOLOGIN)."],
    remediation_short_term=["Revoke any explicit object-level grant that duplicates an existing group-role membership, consolidating access onto the group.", "Document the business justification for every non-obvious role membership found."],
    remediation_long_term=["Adopt a standing quarterly role-and-privilege-audit cadence (see maintenance/routine-maintenance-checklist) rather than only auditing reactively after an incident or ahead of a compliance deadline.", "Move toward a small number of well-documented group roles (e.g. app_readonly, app_readwrite, reporting) with individual login roles granted membership only in those groups, instead of ad hoc direct grants."],
    production_safety=["Every script in this workflow is a read-only catalog query; nothing here modifies a role or a grant."],
    escalation_criteria=["Any role with rolsuper = true, or an unexplained rolbypassrls = true, is found -- escalate to the security team immediately regardless of audit cadence.", "A role is found with object-level access it has no documented business justification for -- escalate to the role's owning team before revoking, in case the access is load-bearing for an undocumented integration."],
    related_issues=["../unused-and-orphaned-roles/README.md", "../public-schema-exposure/README.md", "../audit-logging-and-iam-auth/README.md"],
    aurora_notes=["Aurora/RDS does not expose a true PostgreSQL superuser; the bootstrap application role is a member of rds_superuser instead, which is intentionally weaker (no filesystem or OS-level access) -- rolsuper should read false for every role you find, and a true value is itself an anomaly worth investigating rather than an expected top-of-hierarchy role."],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_current_role_capabilities", "Confirms what the currently connected auditing role itself can do -- its super/create/replication attributes and its own group memberships -- as context for interpreting the rest of the audit.",
               sb.current_role_privileges(),
               "rolsuper should read false on Aurora for every role, including this one; member_of_roles shows which group roles this auditing session itself belongs to, which determines what the remaining queries in this workflow will actually be able to see.",
               related_scripts="02_all_roles_and_memberships.sql"),
    sql_script("02", "02_all_roles_and_memberships", "Enumerates every non-system role in the cluster along with its login/create/replication attributes and its full group-membership list.",
               """
-- Every role in the cluster (excluding the internal pg_* predefined roles,
-- which are fixed PostgreSQL built-ins, not cluster-specific grants) with
-- its key attributes and the group roles it is a member of.
SELECT
    r.rolname,
    r.rolcanlogin,
    r.rolsuper,
    r.rolcreaterole,
    r.rolcreatedb,
    r.rolreplication,
    r.rolbypassrls,
    r.rolvaliduntil,
    ARRAY(
        SELECT b.rolname
        FROM pg_auth_members m
        JOIN pg_roles b ON b.oid = m.roleid
        WHERE m.member = r.oid
        ORDER BY 1
    )                                                            AS member_of_roles
FROM pg_roles r
WHERE r.rolname NOT LIKE 'pg\\_%'
ORDER BY r.rolname;
""".strip("\n"),
               "rolsuper = true anywhere in this result is an immediate finding on Aurora (see this workflow's escalation criteria). Cross-reference member_of_roles against a documented role-design diagram; any membership you cannot explain is the actual audit finding, not a false positive to dismiss.",
               related_scripts="03_object_level_grants_by_schema.sql"),
    sql_script("03", "03_object_level_grants_by_schema", "Enumerates explicit, individually-granted table/view/materialized-view privileges across all non-system schemas, the grants that bypass group-role membership entirely.",
               """
-- Explicit object-level ACL entries on tables/views/materialized views in
-- every non-system schema. A row only appears here when a grant was made
-- directly against the object (GRANT ... ON object TO role) -- access
-- granted purely through role membership (e.g. the role's group has SELECT
-- on the schema via a default privilege) does not show up as a relacl
-- entry on the object itself, so treat this as a complement to, not a
-- replacement for, 02_all_roles_and_memberships.sql.
SELECT
    n.nspname                                                   AS schema_name,
    c.relname                                                   AS relation_name,
    CASE c.relkind
        WHEN 'r' THEN 'table' WHEN 'p' THEN 'partitioned table'
        WHEN 'v' THEN 'view' WHEN 'm' THEN 'materialized view'
        ELSE c.relkind::text
    END                                                          AS relation_type,
    a.grantee::regrole::text                                    AS grantee,
    a.privilege_type,
    a.is_grantable
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
CROSS JOIN LATERAL aclexplode(c.relacl) AS a
WHERE c.relkind IN ('r', 'p', 'v', 'm')
  AND c.relacl IS NOT NULL
  AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
ORDER BY schema_name, relation_name, grantee;
""".strip("\n"),
               "A grantee of 'public' here means every role in the cluster (including future ones) has that privilege on that specific object -- treat any such row on a table containing customer/financial data as a high-priority finding, not a routine entry; see public-schema-exposure for the schema-level counterpart of this check.",
               related_scripts="../public-schema-exposure/scripts/02_objects_granted_to_public.sql"),
]

# ---------------------------------------------------------------------------
# unused-and-orphaned-roles
# ---------------------------------------------------------------------------
WORKFLOWS.append(_wf(
    slug="unused-and-orphaned-roles",
    title="Unused and Orphaned Roles",
    summary="Roles that exist in the cluster but show no evidence of ongoing legitimate use -- no active or recent connections, no owned objects, and no group-membership purpose -- and are therefore candidates for cleanup, distinct from role-and-privilege-audit's broader 'what can everyone do' inventory.",
    symptoms=["A role-and-privilege-audit turns up roles nobody on the current team recognizes.", "An employee/service offboarding checklist requires confirming a specific role is no longer in use before dropping it."],
    business_impact=["Every unused login-capable role is standing attack surface -- a credential that, if ever compromised, still works, even though no legitimate process uses it -- and every unused role also adds noise that makes the next audit slower and less reliable."],
    root_causes=["A role created for a former employee, a decommissioned service, or a one-off migration/analysis task was never dropped afterward.", "A role still owns objects (so DROP ROLE fails outright) even though nothing connects as that role anymore, because ownership was never reassigned when the role's active use ended."],
    investigation_strategy=["For every non-system role, check current connections, historical objects owned, and whether it is used purely as a group (has members) or an actual login identity.", "Cross-reference candidates against your organization's service/employee inventory before taking any action -- absence of a *current* connection does not prove a role is unused if it connects rarely (e.g. a monthly batch job)."],
    prerequisites=["Read access to pg_roles/pg_stat_activity/pg_class (standard for any authenticated role); an inventory of expected services/employees to cross-reference candidates against."],
    interpretation_guide=["A role with objects_owned = 0, current_connections = 0, and has_members_count = 0 is a strong cleanup candidate, but 'strong candidate' is not 'confirmed safe to drop' -- pg_stat_activity only shows connections that exist right now, not a historical connection log, so a role used only for an infrequent scheduled job can look identical to a truly abandoned one on a single snapshot.", "is_rds_builtin_role = true rows (the rds_* family) are AWS-managed infrastructure roles, not candidates for cleanup regardless of how the other columns look."],
    remediation_immediate=["None -- this is never an emergency workflow; act deliberately, not urgently, when removing access."],
    remediation_short_term=["For a confirmed-abandoned role that still owns objects, reassign ownership (REASSIGN OWNED BY ... TO ...) to an appropriate current role before dropping it, then DROP OWNED BY ... to clear any remaining grants, then DROP ROLE."],
    remediation_long_term=["Add role deactivation (REVOKE the ability to log in via ALTER ROLE ... NOLOGIN, observed for a cooldown period) as a standard step in the employee/service offboarding checklist, ahead of an eventual DROP ROLE, so cleanup does not depend on someone remembering to run this audit."],
    production_safety=["The investigation query (script 01) is read-only. The cleanup runbook (script 02) is a guarded, manual template -- REASSIGN OWNED / DROP OWNED / DROP ROLE are irreversible with respect to the dropped role's identity and must never be run against a candidate that has not been independently confirmed abandoned."],
    escalation_criteria=["A candidate role turns out to still be referenced by application connection-string configuration or infrastructure-as-code even though it shows zero current connections -- treat this as a near-miss and escalate to the owning team before it is actually dropped."],
    related_issues=["../role-and-privilege-audit/README.md", "../../maintenance/routine-maintenance-checklist/README.md"],
    aurora_notes=["Do not include the built-in rds_* roles (rds_superuser, rds_replication, rds_password, rds_iam, and similar) in any cleanup consideration -- these are managed by the Aurora/RDS control plane and are expected to exist regardless of whether they currently have members."],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_candidate_roles_by_activity_and_ownership", "Ranks every non-system role by current connection count, objects owned, and group-membership purpose, surfacing the roles with the least evidence of ongoing legitimate use first.",
               """
-- Cross-references role attributes against current connections and object
-- ownership to surface roles with no visible current activity. Results are
-- ordered with the least-evidence-of-use roles first; this is a starting
-- point for investigation, not an automatic deletion list -- pg_stat_activity
-- reflects only right-now connections, not historical usage.
SELECT
    r.rolname,
    r.rolcanlogin,
    r.rolname LIKE 'rds\\_%'                                     AS is_rds_builtin_role,
    (SELECT count(*) FROM pg_stat_activity a
      WHERE a.usename = r.rolname)                               AS current_connections,
    (SELECT count(*) FROM pg_class c
      WHERE c.relowner = r.oid)                                  AS objects_owned,
    (SELECT count(*) FROM pg_auth_members m
      WHERE m.roleid = r.oid)                                    AS has_members_count,
    (SELECT count(*) FROM pg_auth_members m2
      WHERE m2.member = r.oid)                                   AS member_of_count
FROM pg_roles r
WHERE r.rolname NOT LIKE 'pg\\_%'
ORDER BY is_rds_builtin_role ASC, current_connections ASC, objects_owned ASC, has_members_count ASC, r.rolname;
""".strip("\n"),
               "Focus on rows where is_rds_builtin_role = false, current_connections = 0, objects_owned = 0, and has_members_count = 0 -- these have no current connection, own nothing, and are not serving as a group role for anyone else. Confirm against your service/employee inventory (this snapshot cannot see infrequent, e.g. monthly, legitimate connections) before treating any of them as safe to remove.",
               related_scripts="02_role_cleanup_runbook.md"),
    md_script("02", "02_role_cleanup_runbook", "Guarded, manual runbook for reassigning ownership away from and then dropping a role confirmed abandoned by script 01 and by cross-referencing your service/employee inventory.",
              (
                  "## Before you run anything here\n\n"
                  "1. Confirm the candidate role from `01_candidate_roles_by_activity_and_ownership.sql` "
                  "against your organization's current service/employee inventory -- a zero connection "
                  "count on this snapshot does not prove the role is never used (e.g. a monthly batch "
                  "job).\n"
                  "2. Get a second engineer to independently confirm the same conclusion before "
                  "proceeding -- this is destructive with respect to the role's identity and any "
                  "grants attached to it.\n\n"
                  "## Step 1 -- reassign ownership (only if objects_owned > 0)\n\n"
                  "Replace `legacy_reporting_svc` below with the actual confirmed-abandoned role name, "
                  "and `app_readonly` with the current role that should inherit ownership of whatever "
                  "it owned:\n\n"
                  "```sql\n"
                  "REASSIGN OWNED BY legacy_reporting_svc TO app_readonly;\n"
                  "```\n\n"
                  "## Step 2 -- drop any remaining grants/dependencies owned by the role\n\n"
                  "```sql\n"
                  "DROP OWNED BY legacy_reporting_svc;\n"
                  "```\n\n"
                  "This revokes any privileges the role was separately granted (as opposed to objects "
                  "it owned, already handled in Step 1) and removes any default-privilege entries "
                  "associated with it.\n\n"
                  "## Step 3 -- drop the role\n\n"
                  "```sql\n"
                  "DROP ROLE legacy_reporting_svc;\n"
                  "```\n\n"
                  "This will fail with an explicit dependency error if Steps 1-2 missed something -- "
                  "treat that failure as useful information (something still depends on this role) and "
                  "investigate it rather than forcing the drop through.\n\n"
                  "## Do NOT\n\n"
                  "- Do NOT run `DROP ROLE` directly without Steps 1-2 on a role that owns any object -- "
                  "it will simply fail, but repeatedly attempting workarounds without understanding "
                  "why is how ownership gets reassigned to the wrong place under time pressure.\n"
                  "- Do NOT drop a role solely because `current_connections` was zero on one snapshot -- "
                  "re-run script 01 at a different time of day/week first if the role's expected usage "
                  "pattern is infrequent.\n"
              ),
              "Follow the three steps in order, confirming the outcome of each before moving to the next. A role that resists Step 3 after Steps 1-2 have run cleanly still has a dependency you have not found yet -- do not force it.",
              required_privileges="Membership in a role with CREATEROLE, or rds_superuser, to REASSIGN OWNED / DROP OWNED / DROP ROLE.",
              related_scripts="01_candidate_roles_by_activity_and_ownership.sql"),
]

# ---------------------------------------------------------------------------
# public-schema-exposure
# ---------------------------------------------------------------------------
WORKFLOWS.append(_wf(
    slug="public-schema-exposure",
    title="Public Schema and Default-Privilege Exposure",
    summary="Reviews exactly what the `public` schema and its objects actually grant to the PUBLIC pseudo-role on this specific database, since PostgreSQL 15 changed the shipped defaults and it is unsafe to assume either the old or the new behavior without verifying.",
    symptoms=["A security review asks 'can any authenticated role create objects in public, or read tables that were only intended for a specific application role'.", "A newly created role can unexpectedly SELECT from a table nobody explicitly granted it access to."],
    business_impact=["Because PostgreSQL 15 changed the built-in default (CREATE on `public` is no longer granted to PUBLIC on databases created under PG15+), a cluster upgraded across that boundary, or one with mixed database-creation history, can have inconsistent exposure per database -- assuming a uniform posture across an Aurora PostgreSQL 17 cluster without checking is itself the risk."],
    root_causes=["A database created before the PG15 default change (or restored/migrated from one) still carries the older, more permissive public-schema ACL, since the change only affects newly initialized databases, not existing ones carried forward through an upgrade.", "An explicit `GRANT ... TO PUBLIC` was added at some point (on the schema or on individual objects) for a legitimate but now-forgotten reason.", "`ALTER DEFAULT PRIVILEGES` was set broadly (for all roles, all schemas) rather than scoped to a specific role/schema, silently applying to every future object."],
    investigation_strategy=["Directly test what the PUBLIC pseudo-role can actually do on the `public` schema using has_schema_privilege(), rather than trying to infer it from a potentially-NULL ACL column.", "Check for any ALTER DEFAULT PRIVILEGES entries that apply broadly.", "Check for individual objects inside `public` that were explicitly granted to PUBLIC directly (not just via the schema's own privileges)."],
    prerequisites=["Read access to pg_namespace/pg_default_acl/pg_class (standard for any authenticated role)."],
    interpretation_guide=["public_role_can_create = true means any login-capable role in the cluster can create objects inside the `public` schema -- on Aurora PostgreSQL 17 databases created fresh this is normally false (the PG15+ default); true on such a database is worth understanding, not assuming is fine because 'it has always been that way'.", "public_role_can_use = true (USAGE on the schema) is the PG15+ default and, by itself, is not a finding -- USAGE only allows referencing objects in the schema, not creating or reading them; CREATE and per-object SELECT/INSERT/etc are the privileges that actually matter."],
    remediation_immediate=["None -- this is a review workflow, not an active-incident one, unless a specific unauthorized-access finding from role-and-privilege-audit points here."],
    remediation_short_term=["If public_role_can_create = true and is not a deliberate, documented choice, run `REVOKE CREATE ON SCHEMA public FROM PUBLIC;` (a guarded DDL step, change-managed) to bring the database in line with the current PostgreSQL default.", "Remove any individual object grants to PUBLIC found in script 02 that are not deliberately intended to be readable/writable by every role in the cluster."],
    remediation_long_term=["Scope every ALTER DEFAULT PRIVILEGES statement to a specific role and schema going forward, never a blanket grant, and document each one alongside the schema/role design."],
    production_safety=["All scripts in this workflow are read-only; the REVOKE mentioned in remediation is a DDL change and must go through the same change-management process as any other privilege change, not be run ad hoc from this investigation."],
    escalation_criteria=["public_role_can_create = true is found on a database holding customer or financial data with no documented justification -- escalate to the security team before the next scheduled deploy touches that schema."],
    related_issues=["../role-and-privilege-audit/README.md", "../audit-logging-and-iam-auth/README.md"],
    aurora_notes=["PostgreSQL 15 changed the default so that newly created databases no longer grant CREATE on the `public` schema to PUBLIC (USAGE is still granted) -- Aurora PostgreSQL 17 inherits this upstream default for databases created directly on 17, but a database carried forward from an earlier engine version via in-place major-version upgrade retains whatever ACL it already had. Always verify with has_schema_privilege() rather than assuming either default."],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_public_schema_privilege_posture", "Directly tests what the PUBLIC pseudo-role can do on the `public` schema, and lists any broadly-scoped ALTER DEFAULT PRIVILEGES entries.",
               """
-- has_schema_privilege() answers "can PUBLIC do X on schema public" directly,
-- which is more reliable than reading pg_namespace.nspacl by hand: a NULL
-- nspacl means "the compiled-in default for this object type", and that
-- default itself differs depending on whether this database was created
-- before or after the PostgreSQL 15 public-schema default change -- letting
-- the privilege functions resolve that ambiguity avoids getting it wrong.
SELECT
    'public'                                                     AS schema_name,
    has_schema_privilege('public', 'public', 'CREATE')            AS public_role_can_create,
    has_schema_privilege('public', 'public', 'USAGE')             AS public_role_can_use;
""".strip("\n") + "\n\n" + """
-- Any ALTER DEFAULT PRIVILEGES entries currently in effect, and exactly
-- which grantee/object-type/schema combination they apply to. A row with a
-- NULL applies_to_schema applies cluster-wide across every schema owned by
-- defaclrole -- the broadest, and therefore highest-review-priority, kind
-- of default-privilege entry.
SELECT
    n.nspname                                                    AS applies_to_schema,
    d.defaclrole::regrole::text                                  AS owning_role,
    d.defaclobjtype                                               AS object_type,
    a.grantee::regrole::text                                     AS grantee,
    a.privilege_type
FROM pg_default_acl d
LEFT JOIN pg_namespace n ON n.oid = d.defaclnamespace
CROSS JOIN LATERAL aclexplode(d.defaclacl) AS a
ORDER BY applies_to_schema NULLS FIRST, owning_role, object_type, grantee;
""".strip("\n"),
               "public_role_can_create = true means any login-capable role can create objects in `public` -- confirm this is deliberate. Any default-privilege row with grantee = 'public' silently grants every future object of that type, in that scope, to every role in the cluster -- treat this as high priority regardless of how narrow the object_type looks.",
               related_scripts="02_objects_granted_to_public.sql"),
    sql_script("02", "02_objects_granted_to_public", "Lists individual tables/views/materialized views inside `public` that were explicitly granted directly to the PUBLIC pseudo-role, independent of the schema-level privileges checked in script 01.",
               """
-- Individual objects in the `public` schema with an explicit grant to the
-- PUBLIC pseudo-role (aclexplode grantee = 0 represents PUBLIC). This is
-- distinct from schema-level USAGE/CREATE: an object can be explicitly
-- opened to PUBLIC even when the schema-level defaults are otherwise tight.
SELECT
    c.relname                                                    AS relation_name,
    CASE c.relkind
        WHEN 'r' THEN 'table' WHEN 'p' THEN 'partitioned table'
        WHEN 'v' THEN 'view' WHEN 'm' THEN 'materialized view'
        ELSE c.relkind::text
    END                                                           AS relation_type,
    a.privilege_type,
    a.is_grantable
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
CROSS JOIN LATERAL aclexplode(c.relacl) AS a
WHERE n.nspname = 'public'
  AND c.relacl IS NOT NULL
  AND a.grantee = 0
ORDER BY relation_name, privilege_type;
""".strip("\n"),
               "Every row here is an object readable/writable (per privilege_type) by any authenticated role in the cluster, regardless of that role's own grants -- for a table holding customer or financial data, a SELECT-to-PUBLIC row here is almost always a finding worth revoking, not an intentional design choice.",
               related_scripts="../role-and-privilege-audit/scripts/03_object_level_grants_by_schema.sql"),
]

# ---------------------------------------------------------------------------
# ssl-and-connection-security
# ---------------------------------------------------------------------------
WORKFLOWS.append(_wf(
    slug="ssl-and-connection-security",
    title="SSL/TLS Connection Security",
    summary="Verifies whether client connections to the cluster are actually using SSL/TLS, and whether SSL enforcement is configured at the Aurora parameter-group level -- distinct from a typical PostgreSQL deployment, where SSL enforcement is a postgresql.conf/pg_hba.conf concern rather than a parameter-group one.",
    symptoms=["A security review asks 'are all connections to this cluster encrypted in transit'.", "An application team reports a client-side SSL negotiation error connecting to the cluster."],
    business_impact=["Unencrypted connections to a database holding financial transaction data are both a direct security exposure (credentials and data readable on the network path) and very likely a compliance finding (PCI-DSS and similar frameworks generally require encryption in transit for this kind of data)."],
    root_causes=["The Aurora cluster parameter group's rds.force_ssl parameter is not enabled, so the server accepts both encrypted and unencrypted connections and enforcement is left entirely to each client's own configuration.", "An application or tool is configured with sslmode=disable or sslmode=allow (client-side opt-out) even though the server would accept SSL if requested.", "An older client library or connection pooler defaults to no SSL and was never explicitly configured to require it."],
    investigation_strategy=["Check the current mix of SSL vs. non-SSL connections and, for SSL connections, which protocol version/cipher is in use.", "Check whether rds.force_ssl is enabled at the parameter-group level, which is the authoritative, server-side enforcement mechanism -- not a client-side setting."],
    prerequisites=["pg_monitor role membership to read pg_stat_ssl/pg_stat_activity."],
    interpretation_guide=["A non-zero count of ssl = false rows in the connection mix confirms unencrypted connections currently exist -- ssl = false with rds.force_ssl not enabled means the server is silently allowing them; ssl = false while rds.force_ssl is enabled should not be possible for ordinary client connections, but Aurora's own internal management connections may be exempt, so investigate the specific application_name/usename before assuming a client bypassed enforcement.", "A low/old TLS version (anything below TLSv1.2) on any connection is worth flagging even if the connection is nominally 'using SSL', since an outdated protocol version undermines the intended security guarantee."],
    remediation_immediate=["If unencrypted connections are found carrying sensitive data in an active-incident context, work with the owning application team to force a client-side reconnect with sslmode=require or stronger while the parameter-group change (below) is scheduled."],
    remediation_short_term=["Enable rds.force_ssl on the cluster parameter group (see this workflow's runbook script) once client applications have been confirmed SSL-capable, so the server itself refuses unencrypted connections rather than relying on every client to opt in correctly."],
    remediation_long_term=["Standardize on sslmode=verify-full (certificate validation, not just encryption) in every application's connection configuration, using the Aurora/RDS CA bundle, so connections are also protected against interception via a spoofed endpoint, not just eavesdropping."],
    production_safety=["The SQL investigation scripts here are read-only. Enabling rds.force_ssl is a parameter-group change: for parameters requiring a reboot to take effect, plan it as a maintenance-window activity (see maintenance/parameter-group-change-management), and confirm every client that will connect afterward is SSL-capable before enforcing it cluster-wide."],
    escalation_criteria=["Sensitive/financial-data connections are found using SSL protocol versions below TLSv1.2, or entirely unencrypted, on a production writer -- escalate to the security team regardless of whether rds.force_ssl is already enabled, since a permissive client-side sslmode can still coexist with a lenient server setting."],
    related_issues=["../audit-logging-and-iam-auth/README.md", "../../maintenance/parameter-group-change-management/README.md"],
    aurora_notes=["SSL/TLS enforcement on Aurora PostgreSQL is controlled by the rds.force_ssl parameter on the DB cluster (and/or instance) parameter group, applied via the AWS Console/CLI/infrastructure-as-code -- there is no postgresql.conf-level ssl=on/off toggle to edit directly the way there is on self-managed PostgreSQL, and ALTER SYSTEM cannot set it."],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_current_connection_ssl_mix", "Breaks down current backend connections by whether SSL is in use, and, for SSL connections, the negotiated protocol version and cipher.",
               """
-- Current connection mix by SSL status/protocol/cipher, joined against
-- pg_stat_activity so each row is attributable to an application/user. A
-- row with ssl = false is an unencrypted connection right now.
SELECT
    a.application_name,
    a.usename,
    s.ssl,
    s.version                                                    AS tls_version,
    s.cipher,
    count(*)                                                     AS connection_count
FROM pg_stat_ssl s
JOIN pg_stat_activity a ON a.pid = s.pid
WHERE a.pid <> pg_backend_pid()
GROUP BY a.application_name, a.usename, s.ssl, s.version, s.cipher
ORDER BY s.ssl ASC, connection_count DESC;
""".strip("\n"),
               "Any row with ssl = false is a currently-unencrypted connection -- note its application_name/usename to identify the responsible client for remediation. Among ssl = true rows, a tls_version below TLSv1.2 is also worth flagging even though the connection is nominally encrypted.",
               related_scripts="02_force_ssl_parameter_status.sql"),
    sql_script("02", "02_force_ssl_parameter_status", "Checks whether the Aurora rds.force_ssl parameter is currently enabled on this instance, which is the authoritative server-side SSL enforcement mechanism.",
               """
-- rds.force_ssl is an Aurora/RDS-specific parameter surfaced as an ordinary
-- row in pg_settings on instances where it is defined; it does not exist as
-- a GUC on self-managed PostgreSQL at all, so this is guarded rather than
-- assumed present.
SELECT EXISTS (
    SELECT 1 FROM pg_settings WHERE name = 'rds.force_ssl'
)                                                                AS rds_force_ssl_defined
\\gset

\\if :rds_force_ssl_defined
SELECT name, setting, context, source
FROM pg_settings
WHERE name = 'rds.force_ssl';
\\else
SELECT
    'rds.force_ssl is not defined on this instance -- this is expected on '
    'self-managed/non-RDS PostgreSQL, and would be unexpected on an Aurora '
    'instance. If this is genuinely an Aurora PostgreSQL instance, confirm '
    'you are connected to the instance you intend to check.'               AS notice;
\\endif
""".strip("\n"),
               "setting = '1' (or 'on', depending on engine version's boolean rendering) means the server itself refuses unencrypted connections; setting = '0'/'off' means enforcement is left entirely to each client's own sslmode configuration -- see 03_enabling_force_ssl.md to change this.",
               related_scripts="03_enabling_force_ssl.md"),
    md_script("03", "03_enabling_force_ssl", "Runbook for enabling rds.force_ssl via the Aurora cluster parameter group once client SSL-readiness has been confirmed.",
              (
                  "## Before enabling\n\n"
                  "Confirm every application/service that connects to this cluster is already "
                  "capable of SSL connections (ideally `sslmode=verify-full` with the RDS CA bundle "
                  "installed) using `01_current_connection_ssl_mix.sql` -- enabling `rds.force_ssl` "
                  "before every client is ready will disconnect and then continuously reject any "
                  "client still connecting with `sslmode=disable`.\n\n"
                  "## Enabling via the AWS CLI\n\n"
                  "`rds.force_ssl` is set on the DB cluster parameter group, not per instance:\n\n"
                  "```\n"
                  "aws rds modify-db-cluster-parameter-group \\\n"
                  "  --db-cluster-parameter-group-name <cluster-parameter-group-name> \\\n"
                  "  --parameters \"ParameterName=rds.force_ssl,ParameterValue=1,ApplyMethod=pending-reboot\"\n"
                  "```\n\n"
                  "Confirm the parameter's `ApplyType` via `describe-db-cluster-parameters` before "
                  "assuming it is dynamic -- on many Aurora PostgreSQL engine versions "
                  "`rds.force_ssl` requires a reboot of each instance in the cluster to take effect, "
                  "which is a brief availability interruption per instance and should be scheduled as "
                  "a maintenance-window activity (see maintenance/parameter-group-change-management), "
                  "not applied immediately to a live production writer.\n\n"
                  "## Rolling out safely\n\n"
                  "1. Apply the parameter-group change to a non-production cluster's parameter group "
                  "first and confirm existing non-SSL client configurations there actually fail as "
                  "expected.\n"
                  "2. Update any client still on `sslmode=disable`/`allow` to `require` or stronger.\n"
                  "3. Schedule the reboot for the production cluster's instances during a maintenance "
                  "window, rebooting readers before the writer where failover order matters.\n"
                  "4. Re-run `01_current_connection_ssl_mix.sql` afterward to confirm no connection "
                  "is being silently rejected in a way that surfaces as an application-level outage.\n"
              ),
              "Read the full rollout sequence before applying -- the risk in this change is almost never the parameter itself, it is enforcing it before every client is confirmed ready.",
              safety="LOW RISK WRITE (Aurora DB cluster parameter group change; typically requires a per-instance reboot to take effect -- see runbook)",
              expected_impact="No impact until applied; once applied, any client still connecting without SSL will begin failing to connect immediately after each instance's reboot.",
              required_privileges="IAM permission to modify the DB cluster parameter group (rds:ModifyDBClusterParameterGroup or console equivalent); no PostgreSQL role required for the parameter-group step itself.",
              execution_location=ANY_INSTANCE,
              expected_runtime="Minutes to apply the parameter; a full maintenance-window reboot cycle across the cluster's instances for it to take effect.",
              related_scripts="02_force_ssl_parameter_status.sql"),
]

# ---------------------------------------------------------------------------
# audit-logging-and-iam-auth
# ---------------------------------------------------------------------------
WORKFLOWS.append(_wf(
    slug="audit-logging-and-iam-auth",
    title="Audit Logging (pgaudit) and IAM Database Authentication",
    summary="Reviews two related but distinct access-security controls: whether the pgaudit extension is installed and configured for detailed session/object audit logging, and whether IAM database authentication (via the built-in rds_iam role) is in use as an alternative to password authentication.",
    symptoms=["A compliance review asks for evidence of detailed audit logging of who accessed/modified specific data.", "A security review asks whether database credentials are password-based (a standing secret to rotate/leak) or IAM-token-based (short-lived, tied to an AWS identity)."],
    business_impact=["For a regulated trading platform, an auditable trail of who read or modified specific rows/tables is frequently a direct compliance requirement, not just a best practice; similarly, IAM authentication removes a class of long-lived-password-leak risk that password authentication cannot eliminate on its own."],
    root_causes=["pgaudit was never installed because it must be explicitly requested (a shared_preload_libraries + CREATE EXTENSION change), unlike PostgreSQL's own baseline statement logging.", "Application roles were provisioned with password authentication from the start and nobody has since migrated them to IAM authentication.", "pgaudit is installed but its scope (pgaudit.log) is set too broadly or too narrowly for the actual compliance requirement -- discovered only when someone asks for a specific audit trail and it is not there."],
    investigation_strategy=["Check whether pgaudit is installed and, if so, what its current logging scope is configured to.", "Check which roles are currently members of the built-in rds_iam role, which is how IAM database authentication is granted per role on Aurora."],
    prerequisites=["pg_monitor role membership; read access to pg_extension/pg_settings/pg_auth_members (standard for any authenticated role)."],
    interpretation_guide=["pgaudit_installed = false means no extension-level audit trail exists beyond whatever PostgreSQL's own log_statement/log_min_duration_statement settings capture (which log the statement, but not necessarily in the structured, object-level form pgaudit provides) -- confirm whether this actually satisfies your compliance requirement before assuming logging is 'good enough'.", "A role appearing in the IAM-authenticated members list can connect using a short-lived IAM auth token instead of a static password; a role that legitimately should be using IAM authentication but does not appear here is still relying on a long-lived password credential."],
    remediation_immediate=["None -- this is a review workflow, not an active-incident one."],
    remediation_short_term=["For any role that should be using IAM authentication and is not yet, grant it rds_iam membership and update the connecting application/service to request an IAM auth token instead of a static password (see this workflow's runbook)."],
    remediation_long_term=["If pgaudit is not installed and a compliance requirement genuinely needs object-level audit logging, plan its installation and shared_preload_libraries change as a change-managed maintenance-window activity (see this workflow's runbook and maintenance/parameter-group-change-management, since shared_preload_libraries changes require a reboot).", "Migrate remaining password-authenticated application roles to IAM authentication over time as a standing security posture improvement, prioritizing roles with access to the most sensitive data first."],
    production_safety=["The investigation scripts here are read-only. Installing pgaudit (CREATE EXTENSION plus a shared_preload_libraries parameter-group change) and granting rds_iam membership are both guarded, change-managed steps documented in this workflow's runbook -- neither is executed automatically by any script here."],
    escalation_criteria=["A compliance deadline requires object-level audit evidence and pgaudit is confirmed not installed -- escalate to the platform/compliance team immediately, since installing it requires a reboot-driven maintenance window that needs lead time to schedule."],
    related_issues=["../role-and-privilege-audit/README.md", "../ssl-and-connection-security/README.md"],
    aurora_notes=["IAM database authentication on Aurora PostgreSQL is granted per role by making that role a member of the built-in rds_iam role -- it does not exist as a concept on self-managed PostgreSQL at all, which instead would rely on an external authentication mechanism (LDAP/Kerberos) configured very differently."],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_pgaudit_installation_and_scope", "Checks whether the pgaudit extension is installed and, if so, reports its current logging-scope configuration.",
               """
-- pgaudit must be explicitly installed (shared_preload_libraries entry plus
-- CREATE EXTENSION) -- this script never installs it itself, it only
-- reports current status, and prints an instructional notice instead if it
-- is absent.
SELECT EXISTS (
    SELECT 1 FROM pg_extension WHERE extname = 'pgaudit'
)                                                                AS pgaudit_installed
\\gset

\\if :pgaudit_installed
SELECT extversion AS pgaudit_version
FROM pg_extension
WHERE extname = 'pgaudit';

SELECT name, setting, context, source
FROM pg_settings
WHERE name LIKE 'pgaudit.%'
ORDER BY name;
\\else
SELECT
    'pgaudit is not installed in this database. This script never runs '
    'CREATE EXTENSION automatically (installation is a change-managed, '
    'reboot-driving shared_preload_libraries change) -- see '
    '03_installing_pgaudit_and_granting_iam_auth.md for the guarded '
    'installation runbook if object-level audit logging is required.'      AS notice;
\\endif
""".strip("\n"),
               "If installed, pgaudit.log determines what gets logged (e.g. 'read, write, role' vs. a narrower scope) -- compare the configured scope against your actual compliance requirement rather than assuming any nonempty configuration is sufficient. If not installed, treat this as a gap to close only if a specific compliance requirement needs it -- installing it is not free (added logging volume and overhead) and should be a deliberate decision.",
               related_scripts="02_iam_authenticated_roles.sql"),
    sql_script("02", "02_iam_authenticated_roles", "Lists every role currently granted IAM database authentication via membership in the built-in rds_iam role.",
               """
-- rds_iam membership is how IAM database authentication is granted per role
-- on Aurora/RDS PostgreSQL. A role NOT in this list authenticates using a
-- traditional password (or another configured method) instead.
SELECT
    r.rolname                                                   AS role_name,
    r.rolcanlogin
FROM pg_auth_members m
JOIN pg_roles g ON g.oid = m.roleid
JOIN pg_roles r ON r.oid = m.member
WHERE g.rolname = 'rds_iam'
ORDER BY r.rolname;
""".strip("\n"),
               "Every role listed here can authenticate using a short-lived IAM auth token rather than a static password. Any login-capable role you would expect to see here but do not is still relying on password authentication -- see the runbook for how to add it.",
               related_scripts="03_installing_pgaudit_and_granting_iam_auth.md"),
    md_script("03", "03_installing_pgaudit_and_granting_iam_auth", "Guarded runbook for installing pgaudit (change-managed, reboot-driving) and for granting IAM database authentication to a role.",
              (
                  "## Installing pgaudit\n\n"
                  "pgaudit requires two steps, the first of which needs a reboot to take effect and "
                  "must be scheduled as a maintenance-window activity (see "
                  "maintenance/parameter-group-change-management):\n\n"
                  "1. Add `pgaudit` to the DB cluster parameter group's `shared_preload_libraries`:\n\n"
                  "```\n"
                  "aws rds modify-db-cluster-parameter-group \\\n"
                  "  --db-cluster-parameter-group-name <cluster-parameter-group-name> \\\n"
                  "  --parameters \"ParameterName=shared_preload_libraries,ParameterValue=pgaudit,ApplyMethod=pending-reboot\"\n"
                  "```\n\n"
                  "   If `shared_preload_libraries` already lists other modules (e.g. "
                  "`pg_stat_statements`), include the full comma-separated list -- this parameter is "
                  "not additive across separate calls.\n\n"
                  "2. After the reboot, install the extension itself. This is the one and only place "
                  "in this runbook where `CREATE EXTENSION` appears, and it is intentionally shown "
                  "only as documentation, not as an auto-executing script, because installing an "
                  "extension is a schema-level, change-managed decision:\n\n"
                  "```sql\n"
                  "CREATE EXTENSION pgaudit;\n"
                  "```\n\n"
                  "   Then set `pgaudit.log` (and any other `pgaudit.*` parameter) through the DB "
                  "cluster/instance parameter group -- the same mechanism as `shared_preload_libraries` "
                  "above, not a SQL session command, since Aurora does not support `ALTER SYSTEM` for "
                  "this or any other parameter-group-managed setting:\n\n"
                  "```\n"
                  "aws rds modify-db-cluster-parameter-group \\\n"
                  "  --db-cluster-parameter-group-name <cluster-parameter-group-name> \\\n"
                  "  --parameters \"ParameterName=pgaudit.log,ParameterValue='write\\,ddl\\,role',ApplyMethod=immediate\"\n"
                  "```\n\n"
                  "   choosing a scope (e.g. `write, ddl, role`) that matches your actual compliance "
                  "requirement.\n\n"
                  "## Granting IAM database authentication to a role\n\n"
                  "```sql\n"
                  "GRANT rds_iam TO app_readonly;\n"
                  "```\n\n"
                  "After granting, update the connecting application/service to request an IAM auth "
                  "token (via the AWS SDK's `generate-db-auth-token` or equivalent) instead of a "
                  "static password, and confirm `pg_hba.conf`-equivalent Aurora auth configuration "
                  "permits IAM auth for that role's connection path -- this is itself managed through "
                  "the parameter group / AWS Console, not a SQL statement.\n\n"
                  "## Verifying afterward\n\n"
                  "Re-run `01_pgaudit_installation_and_scope.sql` and `02_iam_authenticated_roles.sql` "
                  "to confirm both changes took effect as intended.\n"
              ),
              "Both changes here are deliberate, change-managed steps -- pgaudit installation because it requires a reboot and adds ongoing logging overhead, and rds_iam grants because they change how an application authenticates and require a coordinated client-side update.",
              safety="LOW RISK WRITE (shared_preload_libraries parameter-group change requires a reboot; CREATE EXTENSION and GRANT are schema/role changes -- see runbook for sequencing)",
              expected_impact="pgaudit adds per-statement logging overhead proportional to its configured scope once installed and enabled; granting rds_iam has no impact until the client is updated to use an IAM token.",
              required_privileges=TABLE_OWNER_OR_DDL + " Additionally, IAM permission to modify the DB cluster parameter group, and CREATEROLE (or rds_superuser) to GRANT rds_iam to another role.",
              execution_location=ANY_INSTANCE,
              expected_runtime="Minutes for the GRANT; a full maintenance-window reboot cycle for the shared_preload_libraries change to take effect.",
              related_scripts="01_pgaudit_installation_and_scope.sql, 02_iam_authenticated_roles.sql"),
]

# ---------------------------------------------------------------------------
# row-level-security-review
# ---------------------------------------------------------------------------
WORKFLOWS.append(_wf(
    slug="row-level-security-review",
    title="Row-Level Security Coverage Review",
    summary="Reviews which tables actually have row-level security (RLS) enabled, what their policies allow, and which roles can bypass RLS entirely -- the control that decides whether a single compromised or over-broad application role can read every customer's wallet balance and ledger history, or only the rows it is entitled to.",
    symptoms=["A security or compliance review asks how per-customer data isolation is enforced inside the database itself, not just in the application's query layer.", "A support/reporting role that was only meant to see one customer's records is found returning rows for every customer.", "RLS was enabled on a sensitive table at some point, but nobody can currently state which policies apply or whether the application role is exempt from them."],
    business_impact=["On an exchange, wallet balances, deposit/withdrawal history, and the ledger are per-customer data: if isolation is enforced only in application code, any SQL path that bypasses that code (an ad hoc analyst query, a reporting tool, a compromised service credential) reads everything, which is simultaneously a customer-privacy breach, an insider-risk exposure, and a reportable compliance incident.", "RLS enabled but silently bypassed (owner tables without FORCE, or a role with rolbypassrls) is arguably worse than no RLS, because the control shows as 'in place' on an audit checklist while providing no actual isolation."],
    root_causes=["RLS was enabled on a table (`relrowsecurity`) but the application connects as the table's owner, and owners are exempt from their own table's policies unless `FORCE ROW LEVEL SECURITY` is also set.", "A role was granted the BYPASSRLS attribute for a one-off backfill or migration and the attribute was never removed.", "Policies exist but are written `USING (true)` for convenience during rollout, so they satisfy the 'policy exists' checkbox without restricting anything.", "New sensitive tables were added by a later migration and nobody extended the RLS design to cover them, so isolation is inconsistent across tables that hold equally sensitive data."],
    investigation_strategy=["Inventory every table in non-system schemas with its RLS enabled/forced flags and its policy count, so tables holding sensitive data with zero policies stand out immediately.", "Read the actual policy definitions (command, roles, USING and WITH CHECK expressions) rather than trusting that a non-zero policy count means meaningful restriction.", "Identify every role that can bypass RLS outright -- BYPASSRLS holders and table owners on tables without FORCE -- since each one is a complete exemption from whatever the policies say.", "Drill into one specific high-sensitivity table (wallets by default) end to end: RLS flags, policies, and the object-level grants that determine who reaches the table at all."],
    prerequisites=["Read access to pg_class/pg_policy/pg_policies/pg_roles (available to any authenticated role; `pg_policies` shows policies on tables the current role can see).", "A documented statement of which tables are expected to be per-customer isolated -- without it, this workflow can report the current posture but not whether that posture is correct."],
    interpretation_guide=["`rls_enabled = false` on a table holding per-customer financial data is the headline finding -- no policy in the database restricts any role's row visibility on that table; isolation, if any, exists only in application code.", "`rls_enabled = true` with `rls_forced_for_owner = false` means the table owner sees and modifies every row regardless of policy. If the application connects as the owner (a very common pattern after a migration tool created the tables), RLS is effectively inert for the application's own traffic.", "A policy with a `qual` of `true` (or no `qual` at all for a permissive SELECT policy) restricts nothing; count it as absent, not as coverage.", "Any role with `rolbypassrls = true` is exempt from every policy on every table -- treat each one as a standing exception that needs a written justification, and expect that list to be empty or near-empty in steady state.", "`policy_count > 0` with `cmd` values covering only SELECT means INSERT/UPDATE/DELETE paths are unrestricted -- a role that can write can then write rows attributed to another customer even though it cannot read them."],
    remediation_immediate=["If an active incident involves a role reading rows it should not, determine from this workflow's output whether the role is exempt (BYPASSRLS or owner-without-FORCE) or simply covered by a permissive policy -- that distinction decides whether containment means revoking an attribute or fixing a policy, and they are not interchangeable."],
    remediation_short_term=["Remove the BYPASSRLS attribute from any role that does not have a written, current justification for it (guarded runbook, script 04).", "Add `FORCE ROW LEVEL SECURITY` on tables where RLS is enabled but the application connects as the owner, so the owner is subject to its own policies.", "Replace any `USING (true)` policy with a real predicate tied to the session's tenant/customer context."],
    remediation_long_term=["Make RLS coverage a standing part of the schema-change review: any new table holding per-customer wallet/ledger/order data ships with its policies in the same migration that creates it, not as a follow-up.", "Stop connecting the application as the table owner -- separate the migration/owner role from the runtime application role, so ownership exemptions stop being a silent bypass of the isolation model.", "Re-run this review on a scheduled cadence (see maintenance/routine-maintenance-checklist) so tables added between audits do not accumulate uncovered."],
    production_safety=["Scripts 01-03 are read-only catalog queries and are safe at any time, including during an incident.", "Script 04 is a guarded manual runbook: enabling RLS or altering policies takes a brief ACCESS EXCLUSIVE lock on the table and changes which rows every query returns -- an incorrect policy is indistinguishable from data loss from the application's point of view, so it is never executed automatically."],
    escalation_criteria=["A table holding customer balances, ledger entries, or withdrawal records is found with RLS disabled and no compensating documented control -- escalate to the security/compliance owner the same day.", "A login-capable application or human role is found with `rolbypassrls = true` and no documented justification -- escalate immediately; this is a complete exemption from the isolation model, not a tuning detail.", "Policy definitions found in the database do not match the isolation model the compliance documentation claims is in place -- escalate before changing anything, since the documentation may be describing an intended design that was never implemented."],
    related_issues=["../role-and-privilege-audit/README.md", "../public-schema-exposure/README.md", "../access-anomaly-investigation/README.md"],
    aurora_notes=["Aurora PostgreSQL enforces RLS exactly as community PostgreSQL 17 does -- the difference is who can bypass it: there is no OS-level superuser on Aurora, but members of `rds_superuser` and any role with the BYPASSRLS attribute still read past every policy, so 'no superuser exists on Aurora' is not an argument that the isolation model is safe.", "RLS is evaluated on readers exactly as on the writer, so routing analytics traffic to an Aurora reader does not change which rows a role can see -- a reporting role that is over-permissive on the writer is equally over-permissive on every reader in the cluster."],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_rls_status_by_table", "Inventories every table in a non-system schema with its row-level-security flags, policy count, owner, and size, so sensitive tables with no coverage surface first.",
               """
-- RLS posture for every ordinary/partitioned table outside the system
-- schemas. relrowsecurity is the "RLS is enabled" flag; relforcerowsecurity
-- additionally subjects the table's *owner* to its own policies (owners are
-- exempt by default, which is the single most common reason RLS looks
-- enabled but does not restrict the application).
SELECT
    n.nspname                                                    AS schema_name,
    c.relname                                                    AS table_name,
    c.relrowsecurity                                             AS rls_enabled,
    c.relforcerowsecurity                                        AS rls_forced_for_owner,
    (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid)  AS policy_count,
    pg_get_userbyid(c.relowner)                                  AS table_owner,
    pg_size_pretty(pg_total_relation_size(c.oid))                AS total_size
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
ORDER BY c.relrowsecurity ASC, pg_total_relation_size(c.oid) DESC, schema_name, table_name;
""".strip("\n"),
               "Rows sort with unprotected tables first, largest first -- a large table at the top of this list holding per-customer wallet, ledger, or withdrawal data is the finding. rls_enabled = true with rls_forced_for_owner = false means the owner (often the same role the application connects as) sees every row regardless of policy; confirm which role the application actually connects as before recording that table as protected. policy_count = 0 with rls_enabled = true is a deny-all table for non-owners, which is a functional risk rather than a security one -- verify the application is not silently returning zero rows.",
               related_scripts="02_policy_definitions_and_bypass_roles.sql"),
    sql_script("02", "02_policy_definitions_and_bypass_roles", "Prints the actual USING/WITH CHECK expression of every policy in the database, then lists every role that bypasses RLS entirely.",
               """
-- Actual policy definitions. A non-zero policy count means nothing on its
-- own -- what matters is the qual (the USING expression applied to rows the
-- statement reads) and with_check (applied to rows it writes). A policy with
-- qual = 'true' restricts nothing.
SELECT
    schemaname                                                   AS schema_name,
    tablename                                                    AS table_name,
    policyname                                                   AS policy_name,
    permissive,
    roles                                                        AS applies_to_roles,
    cmd                                                          AS applies_to_command,
    qual                                                         AS using_expression,
    with_check                                                   AS with_check_expression
FROM pg_policies
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY schema_name, table_name, policy_name;
""".strip("\n") + "\n\n" + """
-- Roles that bypass row-level security outright. rolbypassrls is a role
-- attribute, not a grant, so it does not appear in any object's ACL and is
-- easy to miss in an object-centric privilege audit. rds_superuser members
-- are listed alongside it because they can set the attribute on themselves.
SELECT
    r.rolname                                                    AS role_name,
    r.rolcanlogin,
    r.rolbypassrls,
    r.rolsuper,
    EXISTS (
        SELECT 1
        FROM pg_auth_members m
        JOIN pg_roles g ON g.oid = m.roleid
        WHERE m.member = r.oid
          AND g.rolname = 'rds_superuser'
    )                                                            AS is_rds_superuser_member
FROM pg_roles r
WHERE r.rolname NOT LIKE 'pg\\_%'
  AND (r.rolbypassrls OR r.rolsuper)
ORDER BY r.rolcanlogin DESC, r.rolname;
""".strip("\n"),
               "Read using_expression literally: `true`, or an expression that does not reference any session/tenant context, means the policy admits every row for the roles it applies to. applies_to_command = 'SELECT' only means write paths are unrestricted -- a role could insert ledger rows attributed to a customer it cannot read. In the second result set, every login-capable role with rolbypassrls = true is a standing, total exemption from all of the policies above; the expected steady-state size of that list is zero.",
               related_scripts="03_rls_coverage_for_sensitive_table.sql"),
    sql_script("03", "03_rls_coverage_for_sensitive_table", "End-to-end RLS review of one specific high-sensitivity table -- flags, policies, and object-level grants -- defaulting to public.wallets and guarded so it prints a notice rather than failing if that table does not exist.",
               """
-- Focused, end-to-end review of one table. The default target is
-- public.wallets, the table most exchange schemas use for per-customer
-- balances; change the two variables below to review any other sensitive
-- table (public.ledger_entries, public.withdrawals, and so on).
--
-- to_regclass() is used rather than a bare ::regclass cast so that a
-- schema which names this table differently produces an instructional
-- notice instead of a "relation does not exist" parse failure.
\\set schema_name 'public'
\\set table_name 'wallets'

SELECT to_regclass(:'schema_name' || '.' || :'table_name') IS NOT NULL AS target_table_exists
\\gset

\\if :target_table_exists
SELECT
    n.nspname                                                    AS schema_name,
    c.relname                                                    AS table_name,
    c.relrowsecurity                                             AS rls_enabled,
    c.relforcerowsecurity                                        AS rls_forced_for_owner,
    pg_get_userbyid(c.relowner)                                  AS table_owner,
    (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid)  AS policy_count
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.oid = to_regclass(:'schema_name' || '.' || :'table_name');

SELECT
    policyname                                                   AS policy_name,
    permissive,
    roles                                                        AS applies_to_roles,
    cmd                                                          AS applies_to_command,
    qual                                                         AS using_expression,
    with_check                                                   AS with_check_expression
FROM pg_policies
WHERE schemaname = :'schema_name'
  AND tablename = :'table_name'
ORDER BY policy_name;

SELECT
    grantee,
    privilege_type,
    is_grantable
FROM information_schema.table_privileges
WHERE table_schema = :'schema_name'
  AND table_name = :'table_name'
ORDER BY grantee, privilege_type;
\\else
SELECT
    'The configured target table does not exist in this database. Set the '
    'schema_name and table_name variables at the top of this script to a '
    'table that does exist (use 01_rls_status_by_table.sql to pick the '
    'highest-sensitivity uncovered table) and re-run.'                     AS notice;
\\endif
""".strip("\n"),
               "Read the three result sets together: the first says whether the control is active and whether the owner is exempt, the second says whether the policies actually restrict anything, and the third says which roles reach the table at all. A table with strong policies but a SELECT grant to a broad group role still exposes exactly as many rows as its weakest policy allows for that group. If the notice row appears instead, the default table name does not match this schema -- pick a real one from script 01 rather than concluding there is nothing sensitive here.",
               required_privileges=PG_MONITOR + " Reading `information_schema.table_privileges` additionally shows only grants involving roles the current role is a member of or can otherwise see, so a full grant picture may require an ownership-level or `pg_read_all_stats`-plus-ownership role.",
               related_scripts="04_enabling_row_level_security.md"),
    md_script("04", "04_enabling_row_level_security", "Guarded runbook for enabling RLS, adding a tenant-isolation policy, forcing it for the table owner, and removing a BYPASSRLS attribute -- with lock behavior and rollback for each step.",
              (
                  "## Before you run anything here\n\n"
                  "1. Complete scripts 01-03 and write down, for the target table, the current "
                  "`rls_enabled` / `rls_forced_for_owner` values, the existing policy list, and the "
                  "role the application actually connects as.\n"
                  "2. Confirm with the owning application team which column carries the tenant/customer "
                  "identity and how the session communicates it (a `SET` of a custom GUC per request, "
                  "or a per-customer role). A policy written against the wrong column silently returns "
                  "the wrong rows.\n"
                  "3. Test the whole sequence on a non-production clone with production-like traffic "
                  "first. An over-restrictive policy presents to the application as missing data, and "
                  "on a trading platform missing wallet rows is an availability incident.\n\n"
                  "## Lock behavior\n\n"
                  "`ALTER TABLE ... ENABLE ROW LEVEL SECURITY`, `... FORCE ROW LEVEL SECURITY`, and "
                  "`CREATE POLICY` each take a brief `ACCESS EXCLUSIVE` lock on the table. The "
                  "statements themselves are catalog-only and complete in milliseconds, but acquiring "
                  "that lock behind a long-running transaction queues every subsequent query on the "
                  "table behind it. Always set a short `lock_timeout` first and retry rather than "
                  "waiting:\n\n"
                  "```sql\n"
                  "SET lock_timeout = '3s';\n"
                  "```\n\n"
                  "## Step 1 -- add the policy while RLS is still disabled\n\n"
                  "Creating the policy first means it is already in place the instant RLS is switched "
                  "on, rather than leaving a window in which RLS is enabled with no policy (which "
                  "denies all rows to non-owners):\n\n"
                  "```sql\n"
                  "CREATE POLICY wallets_tenant_isolation ON public.wallets\n"
                  "    FOR ALL\n"
                  "    TO app_readwrite\n"
                  "    USING (customer_id = current_setting('app.current_customer_id', true)::bigint)\n"
                  "    WITH CHECK (customer_id = current_setting('app.current_customer_id', true)::bigint);\n"
                  "```\n\n"
                  "The `true` second argument to `current_setting` makes it return NULL instead of "
                  "erroring when the application has not set the GUC -- with the comparison above, an "
                  "unset GUC yields NULL and therefore no rows, which fails closed. Verify that is the "
                  "behavior you want before deploying; failing closed is correct for wallet data but "
                  "will break any batch job that legitimately reads across customers.\n\n"
                  "Rollback: `DROP POLICY wallets_tenant_isolation ON public.wallets;`\n\n"
                  "## Step 2 -- enable RLS\n\n"
                  "```sql\n"
                  "ALTER TABLE public.wallets ENABLE ROW LEVEL SECURITY;\n"
                  "```\n\n"
                  "Rollback: `ALTER TABLE public.wallets DISABLE ROW LEVEL SECURITY;` -- this restores "
                  "unrestricted visibility immediately and is the correct emergency action if the "
                  "application starts returning empty result sets after Step 2.\n\n"
                  "## Step 3 -- force RLS for the owner (only if the application connects as the owner)\n\n"
                  "```sql\n"
                  "ALTER TABLE public.wallets FORCE ROW LEVEL SECURITY;\n"
                  "```\n\n"
                  "This is the step that actually closes the ownership bypass, and it is also the step "
                  "most likely to break a migration tool or maintenance job that legitimately needs to "
                  "see all rows. Confirm every such job either connects as a different role or has its "
                  "own policy before running it.\n\n"
                  "Rollback: `ALTER TABLE public.wallets NO FORCE ROW LEVEL SECURITY;`\n\n"
                  "## Step 4 -- remove an unjustified BYPASSRLS attribute\n\n"
                  "```sql\n"
                  "ALTER ROLE legacy_backfill_svc NOBYPASSRLS;\n"
                  "```\n\n"
                  "Rollback: `ALTER ROLE legacy_backfill_svc BYPASSRLS;`. Removing the attribute takes "
                  "effect for that role's *new* transactions; an in-flight session keeps its current "
                  "behavior for the remainder of its transaction, so re-run script 02 after the role's "
                  "sessions have cycled to confirm.\n\n"
                  "## Do NOT\n\n"
                  "- Do NOT enable RLS on a table before its policy exists unless you intend an "
                  "immediate deny-all for non-owners.\n"
                  "- Do NOT write `USING (true)` as a temporary measure to get the change deployed -- "
                  "it satisfies the audit checkbox while providing no isolation, which is the exact "
                  "failure mode this workflow exists to find.\n"
                  "- Do NOT run any step here without `lock_timeout` set, on a table that is in the "
                  "hot path of order placement or settlement.\n"
              ),
              "Run the steps in order (policy, enable, force, then attribute cleanup) and verify with script 03 after each one. If the application begins returning empty result sets, the correct immediate action is the Step 2 rollback (`DISABLE ROW LEVEL SECURITY`), not editing the policy under time pressure.",
              expected_impact="Each statement takes a brief ACCESS EXCLUSIVE lock (milliseconds of catalog work, but it queues behind and then blocks concurrent access on the table). Once enabled, every query against the table returns a restricted row set -- an incorrect policy presents to the application as missing data.",
              required_privileges=TABLE_OWNER_OR_DDL + " Removing a BYPASSRLS attribute additionally requires CREATEROLE or rds_superuser membership.",
              prerequisites="Scripts 01-03 completed for the target table; the tenant-identity column and session-context mechanism confirmed with the owning application team; the sequence rehearsed on a non-production clone.",
              execution_location=WRITER_PREFERRED,
              expected_runtime="Milliseconds per statement once the lock is acquired; the surrounding verification and rollout is a change-managed exercise.",
              related_scripts="03_rls_coverage_for_sensitive_table.sql"),
]

# ---------------------------------------------------------------------------
# credential-and-authentication-hygiene
# ---------------------------------------------------------------------------
WORKFLOWS.append(_wf(
    slug="credential-and-authentication-hygiene",
    title="Credential and Authentication Hygiene",
    summary="Reviews how login roles actually authenticate and how long their credentials stay valid -- password expiry (`rolvaliduntil`), per-role connection limits, password hashing strength, IAM authentication coverage, and the connection-logging settings that make a credential compromise detectable after the fact.",
    symptoms=["A security review asks when each database credential was last rotated and what forces rotation if nobody remembers to do it.", "A service account's password is known to have been exposed (committed to a repository, pasted into a ticket, present in a container image) and the team needs to know exactly which roles are affected and how to rotate safely.", "Connections from a role that should have been decommissioned continue to succeed because its password never expired."],
    business_impact=["A long-lived static database password with access to wallet, ledger, or order-book tables is the single highest-value credential on an exchange platform -- it grants direct data access with no application-layer authorization in front of it, and unlike an application API key it is rarely rotated on a schedule.", "Without `rolvaliduntil` set and without connection logging, a leaked credential remains valid indefinitely and its use is indistinguishable from legitimate traffic, which turns a containable incident into an unbounded one and makes the post-incident forensic question 'what did they access' unanswerable."],
    root_causes=["Roles were created with `CREATE ROLE ... LOGIN PASSWORD '...'` and no `VALID UNTIL` clause, so the credential never expires and rotation depends entirely on someone remembering.", "Application credentials live in a configuration file or secret store with no rotation automation, so rotation is a manual, coordinated, deploy-coupled task that gets deferred indefinitely.", "`log_connections`/`log_disconnections` are off (the Aurora default for both is off), so there is no record of which credential connected from where.", "Roles that could authenticate via IAM (short-lived tokens) were provisioned with passwords instead and never migrated.", "`rolconnlimit` is left at -1 (unlimited) for every role, so a compromised or misbehaving credential can consume the entire connection pool as well as read data."],
    investigation_strategy=["Inventory every login-capable role with its expiry date, connection limit, and whether it is IAM-enabled, ordered so never-expiring password roles surface first.", "Check the cluster's authentication-relevant settings (password hashing algorithm, connection logging, SSL enforcement, session timeouts), all of which are parameter-group-managed on Aurora rather than editable in a configuration file.", "Check per-role and per-database setting overrides, which can quietly weaken a cluster-wide default for exactly the role you are auditing.", "Rotate or harden through the guarded runbook only after the full picture is known -- rotation without coordination disconnects the application."],
    prerequisites=["Read access to pg_roles/pg_settings/pg_db_role_setting (available to any authenticated role). `pg_read_all_settings` membership gives visibility of settings whose values are otherwise restricted; note that password hashes themselves live in `pg_authid` and are deliberately not readable by non-superusers -- this workflow audits credential *policy*, not credential *material*.", "An inventory of which roles are human, which are service accounts, and which secret store holds each service account's password."],
    interpretation_guide=["`rolvaliduntil IS NULL` on a login-capable role means the password never expires. On a role with access to financial data this is the primary finding of this workflow, not a minor note.", "A `rolvaliduntil` already in the past on a role that is still connecting means the role is authenticating by some other means (IAM token, or a trust/peer-style path) -- the expiry did not lock it out, so investigate which mechanism is actually in use rather than assuming the credential is dead.", "`uses_iam_auth = true` means that role can present a short-lived AWS-issued token instead of a static password, which removes the long-lived-secret risk for that role; combined with `rolvaliduntil` in the past, it is a deliberately password-disabled, IAM-only role and is a good end state.", "`password_encryption = scram-sha-256` is the expected value; `md5` indicates a legacy configuration and any role whose password was set under it still has an md5 verifier stored until its password is re-set, even after the setting itself is changed.", "`rolconnlimit = -1` on a service role means one misbehaving or compromised client can exhaust `max_connections` for everyone; see connections/connection-exhaustion for what that looks like when it happens.", "Any row in the per-role settings result that sets a security-relevant parameter for a single role deserves a written justification -- a role-scoped override of a cluster-wide default is easy to set and very easy to forget."],
    remediation_immediate=["If a specific credential is known to be exposed right now, the containment order is: set a new password first, then confirm the application has picked it up, then expire the old one -- and only disable login (`NOLOGIN`) immediately if the exposure is being actively exploited, accepting that this disconnects legitimate traffic on the same role."],
    remediation_short_term=["Set a `VALID UNTIL` date on every password-authenticated login role so rotation becomes enforced rather than remembered (guarded runbook, script 03).", "Set a realistic `rolconnlimit` per service role, sized from the application's pool configuration plus headroom, so no single credential can exhaust the cluster's connection budget.", "Enable `log_connections` (and `log_disconnections`) on the parameter group so credential use is attributable after the fact."],
    remediation_long_term=["Migrate service roles from static passwords to IAM database authentication, prioritizing roles with access to wallet/ledger data, so the standing secret disappears entirely for those paths (see audit-logging-and-iam-auth).", "Automate rotation end to end via the secret store, with the dual-credential pattern described in the runbook, so a rotation never requires a coordinated human deploy.", "Add credential expiry and connection-limit checks to the scheduled security review so new roles cannot silently reintroduce a never-expiring password (see maintenance/routine-maintenance-checklist)."],
    production_safety=["Scripts 01 and 02 are read-only and safe at any time. They deliberately do not read `pg_authid`, so they never touch password verifier material.", "Script 03 is a guarded manual runbook. `ALTER ROLE ... PASSWORD` takes effect for *new* connections only -- existing sessions keep working until they reconnect, which is what makes the dual-credential rotation sequence safe, and also what makes an unannounced rotation look fine for hours and then fail at the next pool refresh.", "Never paste a real password into a ticket, a shared terminal recording, or an unencrypted runbook copy; the runbook shows the statement shape, and the actual secret should come from the secret store at execution time."],
    escalation_criteria=["A credential with access to wallet, ledger, or settlement tables is confirmed exposed -- escalate to security incident response immediately and in parallel with, not after, the rotation work.", "A login-capable role is found that no current team owns and whose password never expires -- escalate to the security team before dropping or disabling it, since an unowned but load-bearing credential can be behind an undocumented integration (see unused-and-orphaned-roles).", "`log_connections` is off on a cluster subject to an audit requirement for authentication records -- escalate to the platform team, since enabling it is a parameter-group change with lead time."],
    related_issues=["../role-and-privilege-audit/README.md", "../audit-logging-and-iam-auth/README.md", "../access-anomaly-investigation/README.md", "../../connections/connection-exhaustion/README.md"],
    aurora_notes=["Aurora has no editable `pg_hba.conf`: which authentication methods are accepted, and from which networks, is decided by the DB cluster/instance parameter group (for example `rds.force_ssl`), the cluster's VPC security groups, and IAM authentication configuration -- so 'tighten pg_hba' is never the remediation on Aurora, and any runbook that says so was written for self-managed PostgreSQL.", "Aurora provides the built-in `rds_password` role: when password-command restriction is in effect on the cluster, roles need `rds_password` membership (or `rds_superuser`) to set or change passwords, including their own. A rotation that fails with a permissions error despite CREATEROLE is usually this, not a syntax problem.", "IAM database authentication issues short-lived tokens tied to an AWS identity, which is the cleanest way to eliminate a standing password for a service role; it is granted per role via `rds_iam` membership and requires a corresponding client-side change to request a token instead of reading a password from configuration."],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_login_roles_expiry_and_limits", "Inventories every login-capable role with its password expiry, connection limit, IAM-auth status, and elevated attributes, ordered so never-expiring password credentials surface first.",
               """
-- Credential policy for every login-capable role. This reads pg_roles only:
-- pg_authid (which holds the actual password verifiers) is deliberately not
-- touched, so no credential material is ever returned by this script.
--
-- rolvaliduntil is the only expiry mechanism PostgreSQL itself enforces for
-- password authentication; a NULL value means the password never expires.
SELECT
    r.rolname                                                    AS role_name,
    r.rolvaliduntil                                              AS password_valid_until,
    CASE
        WHEN r.rolvaliduntil IS NULL      THEN 'never expires'
        WHEN r.rolvaliduntil <= now()     THEN 'already expired'
        ELSE 'expires in ' || date_trunc('day', r.rolvaliduntil - now())::text
    END                                                          AS expiry_status,
    r.rolconnlimit                                               AS connection_limit,
    EXISTS (
        SELECT 1
        FROM pg_auth_members m
        JOIN pg_roles g ON g.oid = m.roleid
        WHERE m.member = r.oid
          AND g.rolname = 'rds_iam'
    )                                                            AS uses_iam_auth,
    EXISTS (
        SELECT 1
        FROM pg_auth_members m
        JOIN pg_roles g ON g.oid = m.roleid
        WHERE m.member = r.oid
          AND g.rolname = 'rds_superuser'
    )                                                            AS is_rds_superuser_member,
    r.rolcreaterole,
    r.rolreplication,
    r.rolbypassrls,
    (SELECT count(*) FROM pg_stat_activity a WHERE a.usename = r.rolname) AS current_connections
FROM pg_roles r
WHERE r.rolcanlogin
  AND r.rolname NOT LIKE 'pg\\_%'
ORDER BY
    (r.rolvaliduntil IS NULL) DESC,
    is_rds_superuser_member DESC,
    r.rolvaliduntil,
    r.rolname;
""".strip("\n"),
               "The top of this result is the work queue: login roles whose password never expires, superuser-adjacent first. uses_iam_auth = true materially lowers the risk for that row (the credential is a short-lived token, not a stored secret), so treat an IAM-only role with an expired password as a good end state rather than a finding. connection_limit = -1 means unlimited -- acceptable for a human admin role, questionable for a service role that has a fixed pool size on the client side. rolcreaterole/rolreplication/rolbypassrls being true on a service account are each privilege-escalation paths worth a separate justification.",
               related_scripts="02_authentication_settings_and_role_overrides.sql"),
    sql_script("02", "02_authentication_settings_and_role_overrides", "Reports the cluster's authentication-relevant settings and every per-role/per-database setting override that could weaken them for a specific identity.",
               """
-- Authentication- and session-security-relevant settings. All of these are
-- managed through the Aurora DB cluster/instance parameter group rather than
-- a postgresql.conf file, so `source` tells you whether the current value
-- came from the parameter group, a per-role override, or the built-in
-- default. Filtering pg_settings by name in a WHERE clause is safe even for
-- parameters that do not exist on a given engine version -- absent ones
-- simply return no row.
SELECT
    name,
    setting,
    unit,
    context,
    source,
    boot_val                                                     AS default_value
FROM pg_settings
WHERE name IN (
        'password_encryption',
        'ssl',
        'rds.force_ssl',
        'log_connections',
        'log_disconnections',
        'log_statement',
        'log_min_duration_statement',
        'idle_in_transaction_session_timeout',
        'idle_session_timeout',
        'statement_timeout',
        'authentication_timeout',
        'row_security'
    )
ORDER BY name;
""".strip("\n") + "\n\n" + """
-- Per-role and per-database setting overrides (ALTER ROLE ... SET / ALTER
-- DATABASE ... SET). An override here silently replaces the cluster-wide
-- value for that identity, which is a common way a tightened default gets
-- undone for exactly the role that most needed it.
SELECT
    coalesce(d.datname, 'all databases')                         AS applies_to_database,
    coalesce(r.rolname, 'all roles')                             AS applies_to_role,
    s.setconfig                                                  AS setting_overrides
FROM pg_db_role_setting s
LEFT JOIN pg_database d ON d.oid = s.setdatabase
LEFT JOIN pg_roles r ON r.oid = s.setrole
ORDER BY applies_to_database, applies_to_role;
""".strip("\n"),
               "password_encryption should read scram-sha-256; md5 means any password set under it is stored as an md5 verifier until that password is re-set, so changing the setting alone does not upgrade existing credentials. log_connections = off means there is no record of which credential connected from which address, which is the single setting that most limits a post-incident investigation (see access-anomaly-investigation). In the second result set, read every setting_overrides array carefully: a role-scoped override of statement_timeout or row_security is legitimate in some designs and a deliberate weakening in others, and only the documented intent distinguishes them.",
               required_privileges=PG_MONITOR + " Some parameters are only visible in full to members of `pg_read_all_settings`; a restricted role sees the row but may see a masked value.",
               related_scripts="03_credential_rotation_and_hardening.md"),
    md_script("03", "03_credential_rotation_and_hardening", "Guarded runbook for rotating a database password without dropping application traffic, setting enforced expiry and connection limits, and hardening authentication settings on Aurora.",
              (
                  "## Before you run anything here\n\n"
                  "1. Complete scripts 01 and 02 so you know which roles are affected, whether the "
                  "role authenticates by password or IAM token, and how many connections it currently "
                  "holds.\n"
                  "2. Identify where the credential is stored on the client side (secret store entry, "
                  "parameter store key, container environment variable) and who owns the deploy that "
                  "picks up a change. A rotation the application cannot pick up is an outage, not a "
                  "security improvement.\n"
                  "3. Never type a real password into a shared terminal or paste one into a ticket. "
                  "Read it from the secret store at execution time, and prefer the psql `\\password` "
                  "meta-command "
                  "(which prompts, hashes client-side, and keeps the plaintext out of the server log "
                  "and your shell history) over an inline `PASSWORD '...'` literal.\n\n"
                  "## Pattern A -- dual-credential rotation (preferred, no downtime)\n\n"
                  "Rather than changing one role's password in place and racing the application to "
                  "pick it up, alternate between two roles that hold identical group memberships:\n\n"
                  "1. Confirm both roles exist and are members of the same group role(s), so they have "
                  "byte-for-byte identical privileges (verify with role-and-privilege-audit script 02 "
                  "before relying on this).\n"
                  "2. Set a new password on the currently *inactive* role:\n\n"
                  "```sql\n"
                  "ALTER ROLE app_readwrite_b WITH PASSWORD 'read-from-secret-store-at-runtime' VALID UNTIL '2026-03-31';\n"
                  "```\n\n"
                  "3. Update the secret store and roll the application so it connects as the newly "
                  "rotated role. Existing sessions on the old role keep working throughout -- "
                  "`ALTER ROLE ... PASSWORD` only affects *new* connections.\n"
                  "4. Once `current_connections` for the old role reaches zero (re-run script 01), "
                  "expire it:\n\n"
                  "```sql\n"
                  "ALTER ROLE app_readwrite_a VALID UNTIL '1970-01-01';\n"
                  "```\n\n"
                  "Rollback at any point before step 4: point the secret store back at the previous "
                  "role, whose credential is still valid. That is the entire reason this pattern is "
                  "preferred over in-place rotation.\n\n"
                  "## Pattern B -- in-place rotation (single role, brief risk window)\n\n"
                  "```sql\n"
                  "ALTER ROLE reporting_ro WITH PASSWORD 'read-from-secret-store-at-runtime' VALID UNTIL '2026-03-31';\n"
                  "```\n\n"
                  "Existing sessions survive; every *new* connection after this statement must use the "
                  "new password. Update the secret store in the same change window, and expect "
                  "authentication failures from any client whose pool refreshes before it picks up the "
                  "new secret. Use this only for roles with a tolerant reconnect path -- never for the "
                  "role serving order placement or settlement.\n\n"
                  "Rollback: re-run the same statement with the previous password (which requires that "
                  "you still have it -- confirm it is retrievable from the secret store's version "
                  "history *before* rotating, not after).\n\n"
                  "## Enforcing expiry on a role that never expires\n\n"
                  "```sql\n"
                  "ALTER ROLE reporting_ro VALID UNTIL '2026-03-31';\n"
                  "```\n\n"
                  "Set the date far enough out that the first enforced rotation is scheduled work, not "
                  "a surprise, and put the date in the team's calendar the same day you set it. A "
                  "`VALID UNTIL` that lapses unnoticed at 03:00 during Asian trading hours is a "
                  "self-inflicted outage.\n\n"
                  "## Capping a service role's connection budget\n\n"
                  "```sql\n"
                  "ALTER ROLE app_readwrite CONNECTION LIMIT 120;\n"
                  "```\n\n"
                  "Size this from the application's configured pool maximum across all instances plus "
                  "headroom for deploy overlap; setting it below the pool's steady-state size causes "
                  "immediate connection failures. Rollback: `ALTER ROLE app_readwrite CONNECTION LIMIT "
                  "-1;`.\n\n"
                  "## Disabling a compromised credential immediately\n\n"
                  "```sql\n"
                  "ALTER ROLE compromised_svc NOLOGIN;\n"
                  "```\n\n"
                  "This prevents new connections but does not terminate existing ones; session "
                  "termination and the surrounding evidence-preservation sequence are covered in "
                  "access-anomaly-investigation's containment runbook. Rollback: `ALTER ROLE "
                  "compromised_svc LOGIN;`.\n\n"
                  "## Aurora-side hardening (parameter group, not SQL)\n\n"
                  "`password_encryption`, `log_connections`, `log_disconnections`, and `rds.force_ssl` "
                  "are all set on the DB cluster parameter group -- `ALTER SYSTEM` is not available on "
                  "Aurora:\n\n"
                  "```\n"
                  "aws rds modify-db-cluster-parameter-group \\\n"
                  "  --db-cluster-parameter-group-name <cluster-parameter-group-name> \\\n"
                  "  --parameters \"ParameterName=log_connections,ParameterValue=1,ApplyMethod=immediate\"\n"
                  "```\n\n"
                  "Confirm each parameter's apply type before assuming it is dynamic, and expect "
                  "`log_connections` to add one log line per connection -- on a cluster with an "
                  "aggressive connection churn pattern that is a meaningful log-volume increase, which "
                  "is itself an argument for fixing the churn (see connections/connection-exhaustion).\n\n"
                  "## Do NOT\n\n"
                  "- Do NOT rotate a shared credential in place during peak trading hours; use the "
                  "dual-credential pattern or wait for a low-volume window.\n"
                  "- Do NOT set `VALID UNTIL` to a near-term date on a role whose owner you have not "
                  "spoken to -- an expiring credential fails closed, at the worst possible moment, "
                  "with an authentication error that looks nothing like a scheduled change.\n"
                  "- Do NOT assume a rotation succeeded because the `ALTER ROLE` returned without "
                  "error; confirm by watching the old role's `current_connections` drain to zero in "
                  "script 01.\n"
              ),
              "Choose Pattern A unless the role genuinely has no second identity available. In either pattern the verification step is the same: re-run script 01 and confirm the old credential's connection count reaches zero before expiring it.",
              expected_impact="ALTER ROLE ... PASSWORD/VALID UNTIL/CONNECTION LIMIT are catalog-only and take effect for new connections; existing sessions are unaffected until they reconnect. NOLOGIN blocks all new connections for that role immediately. A parameter-group change affects the whole cluster.",
              required_privileges="CREATEROLE (or rds_superuser) to alter another role; on Aurora clusters with password-command restriction in effect, `rds_password` membership is additionally required to set any password. IAM permission to modify the DB cluster parameter group for the Aurora-side hardening steps.",
              prerequisites="Scripts 01 and 02 completed; the client-side secret store location and its owning deploy process identified; the previous credential confirmed retrievable from secret-store version history before any in-place rotation.",
              execution_location=WRITER_PREFERRED,
              expected_runtime="Milliseconds per statement; the coordinated rollout (secret store update, application restart, draining the old role's connections) is the part that takes a change window.",
              related_scripts="01_login_roles_expiry_and_limits.sql, 02_authentication_settings_and_role_overrides.sql"),
]



