# 03_extension_upgrade_runbook

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `03_extension_upgrade_runbook.md` |
| Purpose | Guarded runbook for applying ALTER EXTENSION ... UPDATE for an extension identified as needing an upgrade by script 02. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only (the query reads/writes state that only exists or is meaningful on the writer) |
| Safety | LOW RISK WRITE (ALTER EXTENSION ... UPDATE; briefly locks the extension's owned objects, does not rewrite table data) |
| Expected impact | Brief lock on objects owned by the extension during the upgrade; a major-version jump can change function signatures/output relied on by application code or other workflows. |
| Required privileges | Table owner, or a role granted the `MAINTAIN` privilege on the table (PostgreSQL 16+), or a role with `pg_maintain` membership. DDL variants additionally require the privileges needed for the specific DDL statement (e.g. ownership to ALTER TABLE). |
| Prerequisites | Full read-only investigation for this workflow completed; maintenance window and second engineer approval obtained. |
| Execution order | Step 03 of workflow `maintenance/extension-upgrade-planning` |
| Related scripts | 01_installed_extension_inventory.sql, 02_extension_version_skew_check.sql |

## How to interpret / use this runbook

Classify the version jump before applying anything -- the runbook itself takes seconds to run, so the actual risk being managed here is an unreviewed behavior change, not the DDL statement's own duration.

---

## Classify the version jump first

Using `02_extension_version_skew_check.sql`'s output, look up the specific installed_version -> latest_available_version jump in the extension's own release notes. A patch-level bump within the same major version is usually safe to apply directly; any major-version change should be tested against a non-production copy of this database first, since it may add/rename columns or change a function's signature that application code or another workflow in this repository (e.g. observability/slow-query-observability's pg_stat_statements queries) depends on.

## Applying the upgrade

```sql
ALTER EXTENSION pg_stat_statements UPDATE;
```

Replace `pg_stat_statements` with the actual extension identified in script 02. `ALTER EXTENSION ... UPDATE` (with no `TO` clause) upgrades to the default (latest available) version; add `TO 'x.y'` to target a specific intermediate version instead if you are deliberately not jumping straight to the latest.

## After applying

1. Re-run `01_installed_extension_inventory.sql` to confirm the new extversion.
2. Re-run any workflow in this repository that specifically depends on that extension (for example, re-run observability/slow-query-observability's pg_stat_statements queries) to confirm nothing broke.
3. Note the upgrade and version in the next routine-maintenance-checklist cycle's tracking ticket.

## Do NOT

- Do NOT run `CREATE EXTENSION` here -- this runbook only covers upgrading an already-installed extension; installing a new extension for the first time is its own separate, deliberate decision (see docs/prerequisites/README.md).
- Do NOT apply a major-version jump directly to production without first testing against a non-production copy, even if the extension's own documentation describes the upgrade as backward compatible.
