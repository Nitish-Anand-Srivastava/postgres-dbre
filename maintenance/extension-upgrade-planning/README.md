# Extension Upgrade Planning

**Category:** Maintenance | **Workflow:** `maintenance/extension-upgrade-planning`

## 1. Problem Description

Plans ALTER EXTENSION ... UPDATE for installed extensions that have a newer version available on this Aurora engine version -- distinguishing routine, low-risk extension updates from ones with a documented behavior change worth testing before applying in production.

## 2. Typical Symptoms

- routine-maintenance-checklist's extension inventory shows an installed extension version older than what is available.
- A newly required feature (e.g. a pg_stat_statements column added in a later extension version) is missing even though the extension itself is installed.

## 3. Business Impact

- An extension left on an old version can be missing bug fixes or new observability columns other workflows in this repository depend on (e.g. pg_stat_statements' per-query WAL/I/O columns), and, on the security side, an outdated extension version can itself be the subject of a CVE.

## 4. Possible Root Causes

- An extension was installed once (at whatever version was current then) and never revisited as the Aurora engine itself was upgraded across versions that bundled newer extension releases.
- ALTER EXTENSION ... UPDATE is not automatic -- installing a newer extension binary via an engine upgrade does not itself update an already-created extension's active SQL-level version in a given database.

## 5. Investigation Strategy

1. Inventory currently installed extensions and their active versions.
2. Compare each installed extension's version against the newest version available on this Aurora engine release.
3. For any extension with an available upgrade, check whether the specific version jump has a documented behavior change (new/renamed columns, changed function signatures) before just running the upgrade.

## 6. Prerequisites

- Table/database-owner-equivalent privilege to run ALTER EXTENSION; access to the extension's own release notes for the specific version jump identified.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_installed_extension_inventory.sql`](scripts/01_installed_extension_inventory.sql) -- Baseline inventory of every extension currently installed and its active version, the starting point for upgrade planning.
2. [`scripts/02_extension_version_skew_check.sql`](scripts/02_extension_version_skew_check.sql) -- Compares each installed extension's active version against the newest version available on this Aurora engine release.
3. [`scripts/03_extension_upgrade_runbook.md`](scripts/03_extension_upgrade_runbook.md) -- Guarded runbook for applying ALTER EXTENSION ... UPDATE for an extension identified as needing an upgrade by script 02.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Aurora PostgreSQL supports a curated, engine-version-specific set of extensions and extension versions -- an extension version shown as available in pg_available_extension_versions is guaranteed compatible with this specific Aurora engine release; do not attempt to install a version from upstream PostgreSQL documentation that is not listed there.

## 8. Interpretation Guide

- upgrade_available = true only tells you a newer version exists on this engine, not that it is risk-free to apply -- a patch-level version bump (e.g. 1.9 to 1.10) is usually safe to apply directly, while a major version bump (e.g. 1.x to 2.x) is more likely to include a schema or function-signature change worth testing against a non-production copy first.
- The naive text-based max() comparison used here can misorder multi-digit version segments (e.g. '1.9' vs '1.10') -- always visually confirm the actual available version list from pg_available_extension_versions rather than trusting the boolean flag alone for anything but a quick first pass.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- N/A -- this is a planning workflow; an extension version being behind current is essentially never itself an active incident.

**Short-term remediation** (hours to days):

- Apply a confirmed low-risk (patch-level) extension upgrade via the guarded runbook during a routine maintenance window.

**Long-term engineering fix** (days to weeks):

- Add extension-version review to the standing routine-maintenance-checklist cadence so upgrades happen incrementally rather than accumulating into a large, higher-risk jump.

## 10. Production Safety

- The investigation scripts are read-only. ALTER EXTENSION ... UPDATE itself is a guarded, change-managed DDL step -- it can briefly hold locks on objects the extension owns and, for some extensions, can change function behavior/output that dependent application code relies on, so it must be tested against a non-production copy first for anything beyond a routine patch bump.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- An installed extension is multiple major versions behind what is available, with no documented upgrade path tested -- escalate for a dedicated upgrade project rather than attempting it as routine maintenance.

## 12. Related Issues

- [routine-maintenance-checklist](../routine-maintenance-checklist/README.md)
- [schema-changes](../../schema-changes/README.md)
