# Maintenance

Recurring, planned maintenance activities that are routine rather than
incident-driven -- as opposed to `vacuum-and-autovacuum/` (bloat/XID
symptoms already occurring) or `incident-response/` (an active outage).
Every workflow here is investigation-first: read-only SQL scripts establish
what needs maintenance and why, and every actual mutating action (a
`REINDEX`, an `ALTER EXTENSION ... UPDATE`, a parameter group change) is
documented as a guarded markdown runbook that a DBA reads and runs
deliberately in a change-managed window -- never something this toolkit
executes on its own.

## Workflows

| Workflow | Summary |
| --- | --- |
| [`routine-maintenance-checklist`](routine-maintenance-checklist/README.md) | A recurring, standing checklist covering vacuum/autovacuum health, index bloat, planner statistics freshness, extension/settings drift, and a pointer to backup verification. |
| [`reindex-strategy`](reindex-strategy/README.md) | Plans a batched, off-peak `REINDEX CONCURRENTLY` campaign across multiple bloated indexes in a cluster, distinct from schema-changes' single-index build guidance. |
| [`extension-upgrade-planning`](extension-upgrade-planning/README.md) | Plans `ALTER EXTENSION ... UPDATE` for installed extensions with a newer version available on the current Aurora engine, distinguishing routine updates from ones with a documented behavior change. |
| [`parameter-group-change-management`](parameter-group-change-management/README.md) | Explains how Aurora's cluster vs. instance parameter groups work, how to tell whether a change needs a reboot, and how to roll a change out safely. |

## Related categories

* [`vacuum-and-autovacuum/table-bloat`](../vacuum-and-autovacuum/table-bloat/README.md) -- symptom-driven bloat/vacuum investigation this category's routine checklist complements.
* [`schema-changes`](../schema-changes/README.md) -- the safe-DDL guidance that `reindex-strategy` and index-related maintenance build on.
* [`automation/health-checks`](../automation/health-checks/README.md) -- scheduling the checks in this category on a recurring basis.
* [`database-health/comprehensive-health-check`](../database-health/comprehensive-health-check/README.md) -- point-in-time health snapshot this category's checklist references.
