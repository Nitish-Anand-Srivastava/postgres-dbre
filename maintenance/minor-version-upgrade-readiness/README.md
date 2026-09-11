# Minor Version Upgrade Readiness

**Category:** Maintenance | **Workflow:** `maintenance/minor-version-upgrade-readiness`

## 1. Problem Description

Establishes, from inside the database, whether this Aurora PostgreSQL cluster is actually ready for a minor engine version upgrade -- current engine version, the in-database conditions that block or complicate an upgrade (prepared transactions, inactive logical replication slots, very long-running transactions), and the extension/statistics work that must follow the upgrade. The upgrade itself is an AWS control-plane action; everything a DBA can verify beforehand and afterward from SQL lives here.

## 2. Typical Symptoms

- An Aurora minor version has been released (or AWS has scheduled an automatic minor version upgrade during the next maintenance window) and nobody has verified the cluster is in a state where it can be upgraded cleanly.
- A previous minor version upgrade took far longer than the expected downtime window, or rolled back, and nobody established why beforehand.
- Query plans regressed immediately after a previous engine upgrade because planner statistics were never refreshed afterward.

## 3. Business Impact

- A minor version upgrade reboots every instance in the cluster: for a trading platform that means order placement, deposits, and withdrawals are interrupted for the duration -- an upgrade started without checking for blockers can extend that interruption from a predictable minute or two into an unbounded incident.
- Minor versions carry security fixes; staying on an unpatched minor version indefinitely is itself a compliance and security exposure for a regulated exchange, so 'never upgrade' is not a safe default.
- Post-upgrade plan regressions on the order-matching and ledger hot paths look identical to a performance incident, but are entirely preventable by a planned post-upgrade statistics refresh.

## 4. Possible Root Causes

- An open prepared (two-phase) transaction pins resources and is a well-known upgrade and vacuum blocker -- an abandoned prepared transaction from a settlement or ledger job that crashed mid-commit is the usual culprit.
- An inactive logical replication slot (a stopped AWS DMS task, a decommissioned CDC consumer) retains WAL and complicates both the upgrade and the cluster's storage footprint.
- Long-running analytical or reporting transactions spanning the intended upgrade window turn a short reboot into a long recovery.
- Planner statistics are not automatically re-collected by an engine upgrade, so a planner change in the new minor version meets stale statistics on the first post-upgrade query.

## 5. Investigation Strategy

1. Record exactly what engine version is running now, from inside the database, so the upgrade's before/after state is documented rather than assumed from the AWS Console alone.
2. Check for in-database upgrade blockers: prepared transactions, replication slots (especially inactive ones), and long-running transactions.
3. Inventory installed extensions, since some require an ALTER EXTENSION ... UPDATE after the engine moves to a new minor version before their newest behavior is available.
4. Plan the post-upgrade statistics refresh and validation before starting, not after a regression appears.

## 6. Prerequisites

- pg_monitor role membership for the read-only scripts; IAM permission to modify the DB cluster for the upgrade itself; an agreed maintenance window; a recent, verified backup (see disaster-recovery/backup-and-restore-validation) before any engine change.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_current_engine_version_inventory.sql`](scripts/01_current_engine_version_inventory.sql) -- Records the exact community and Aurora engine version this cluster is running, as the documented before-state for the upgrade.
2. [`scripts/02_upgrade_blockers_precheck.sql`](scripts/02_upgrade_blockers_precheck.sql) -- Checks the three in-database conditions that most often block or complicate an engine upgrade: prepared transactions, replication slots, and long-running transactions.
3. [`scripts/03_extension_and_settings_upgrade_surface.sql`](scripts/03_extension_and_settings_upgrade_surface.sql) -- Inventories installed extensions and the operationally significant settings, so post-upgrade drift and extension updates can be identified against a recorded baseline.
4. [`scripts/04_minor_version_upgrade_runbook.md`](scripts/04_minor_version_upgrade_runbook.md) -- AWS-side guidance for executing the minor version upgrade itself, including the blue/green alternative for minimizing the interruption.
5. [`scripts/05_post_upgrade_validation_runbook.md`](scripts/05_post_upgrade_validation_runbook.md) -- Guarded runbook for the database-side work an engine upgrade does not do for you: extension updates, planner statistics refresh, and post-upgrade validation.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Aurora PostgreSQL minor version upgrades are applied to the whole cluster and reboot every instance; because all instances share the same distributed storage volume, there is no per-instance data copy, but there is still a real, connection-terminating interruption. AWS can also apply minor versions automatically during the maintenance window when auto minor version upgrade is enabled -- which means an 'unplanned' upgrade can arrive on AWS's schedule rather than yours, so readiness should be a standing state, not a one-off pre-window exercise.
- Aurora exposes its own engine build via the aurora_version() function in addition to the community version() string; both should be recorded before and after an upgrade, since the community major.minor can stay the same across an Aurora-specific patch level.

## 8. Interpretation Guide

- Any row from the prepared-transactions check is a hard blocker to resolve before the upgrade, not a warning to note and proceed past -- a prepared transaction that has been open for days is almost certainly abandoned, but it must still be explicitly committed or rolled back by its owner rather than silently discarded.
- An inactive replication slot (active = false) with a large retained WAL figure is both an upgrade complication and an ongoing storage cost; decide deliberately whether its consumer is coming back before the window, since dropping a slot a live consumer still needs forces that consumer to re-seed from scratch.
- A long-running transaction that will still be open when the window starts does not prevent the upgrade -- the reboot will terminate it -- but it does mean whatever business process owns it (an end-of-day reconciliation, a large archival batch) will fail mid-flight, so coordinate rather than surprise it.
- The absence of blockers is not the same as readiness: a verified recent backup and a rehearsed rollback position (see disaster-recovery/point-in-time-recovery-drill) are part of readiness too.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- N/A -- this is planned maintenance. If a blocker is found, resolving the blocker is the work; the upgrade waits.

**Short-term remediation** (hours to days):

- Clear each blocker found (have the owning service commit or roll back its prepared transaction, retire or restart the consumer behind an inactive slot, reschedule the long-running batch outside the window), then re-run the readiness scripts immediately before the window opens rather than relying on a check from days earlier.

**Long-term engineering fix** (days to weeks):

- Adopt a standing minor-version cadence (upgrade within a defined number of weeks of release) so the cluster never accumulates a large version gap, and wire the readiness scripts into the pre-maintenance pipeline (see automation/health-checks) so the check is automatic rather than remembered.

## 10. Production Safety

- Every SQL script in this workflow is strictly read-only and safe to run at any time, including immediately before the window.
- The upgrade itself is an AWS control-plane action, not a SQL statement: it reboots every instance in the cluster and interrupts every connection. The post-upgrade statistics refresh is a real database operation documented as a guarded runbook.
- Never start an engine upgrade without a verified, restorable backup and a documented decision about how far back a point-in-time restore would have to go if the upgrade goes badly.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- A prepared transaction exists whose owning application/team cannot be identified before the window -- escalate rather than guessing, since rolling back a settlement or ledger two-phase transaction blindly can leave the exchange's books inconsistent with an external counterparty.
- The cluster is several minor versions behind and the accumulated change set can no longer be reviewed as a routine patch bump -- escalate for a scheduled, separately-tested upgrade rather than treating it as routine maintenance.

## 12. Related Issues

- [parameter-group-change-management](../parameter-group-change-management/README.md)
- [extension-upgrade-planning](../extension-upgrade-planning/README.md)
- [planned-maintenance-window-checklist](../planned-maintenance-window-checklist/README.md)
- [backup-and-restore-validation](../../disaster-recovery/backup-and-restore-validation/README.md)
- [xid-wraparound-risk](../../transactions-and-xid/xid-wraparound-risk/README.md)
