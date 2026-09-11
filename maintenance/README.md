# Maintenance

**Category:** `maintenance`

This is the index for the `maintenance/` category: every workflow
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
| [`routine-maintenance-checklist`](routine-maintenance-checklist/README.md) | A recurring, standing checklist covering vacuum/autovacuum health, index bloat, planner statistics freshness, extension/settings drift, and a pointer to backup verification -- the standard set of checks a DBA runs on a regular cadence (weekly/monthly) rather than only reactively during an incident. |
| [`reindex-strategy`](reindex-strategy/README.md) | Plans a batched, off-peak REINDEX CONCURRENTLY campaign across multiple bloated indexes in a cluster -- distinct from schema-changes/concurrent-index-build's single-index build guidance, this workflow is about sequencing and monitoring a multi-index campaign safely. |
| [`extension-upgrade-planning`](extension-upgrade-planning/README.md) | Plans ALTER EXTENSION ... UPDATE for installed extensions that have a newer version available on this Aurora engine version -- distinguishing routine, low-risk extension updates from ones with a documented behavior change worth testing before applying in production. |
| [`parameter-group-change-management`](parameter-group-change-management/README.md) | Explains how Aurora's cluster vs. instance parameter groups work, how to tell whether a specific parameter change needs a reboot, and how to roll a change out safely -- the foundational mechanism every other workflow in this repository refers to whenever it says a setting must be changed via the parameter group rather than SQL. |
| [`minor-version-upgrade-readiness`](minor-version-upgrade-readiness/README.md) | Establishes, from inside the database, whether this Aurora PostgreSQL cluster is actually ready for a minor engine version upgrade -- current engine version, the in-database conditions that block or complicate an upgrade (prepared transactions, inactive logical replication slots, very long-running transactions), and the extension/statistics work that must follow the upgrade. The upgrade itself is an AWS control-plane action; everything a DBA can verify beforehand and afterward from SQL lives here. |
| [`statistics-maintenance`](statistics-maintenance/README.md) | The standing maintenance workflow for planner statistics: which tables are drifting away from their last ANALYZE, whether per-table autovacuum/analyze settings are tuned for the tables that actually need it, and whether columns on the hot trading paths need a raised statistics target or an extended (multi-column) statistics object. This is the preventive counterpart to the reactive stale-statistics investigation in query-optimization. |
| [`planned-maintenance-window-checklist`](planned-maintenance-window-checklist/README.md) | The wrapper procedure around any planned, disruptive maintenance on this cluster -- an engine upgrade, a reboot for a static parameter change, a failover drill, an instance class change, or a large schema migration. It defines what to verify before the window opens, what to hold as the go/no-go decision, and what to verify afterward before declaring the window closed and handing the platform back to trading. |

## Related Categories

- [`database-health/comprehensive-health-check`](../../database-health/comprehensive-health-check/README.md)
- [`database-health/daily-health-check`](../../database-health/daily-health-check/README.md)
- [`disaster-recovery/backup-and-restore-validation`](../../disaster-recovery/backup-and-restore-validation/README.md)
- [`disaster-recovery/cluster-failover-drill`](../../disaster-recovery/cluster-failover-drill/README.md)
- [`schema-changes`](../../schema-changes/README.md)
- [`schema-changes/concurrent-index-build`](../../schema-changes/concurrent-index-build/README.md)
- [`security-and-access/audit-logging-and-iam-auth`](../../security-and-access/audit-logging-and-iam-auth/README.md)
- [`security-and-access/ssl-and-connection-security`](../../security-and-access/ssl-and-connection-security/README.md)
- [`tables-and-indexes/index-bloat`](../../tables-and-indexes/index-bloat/README.md)
- [`tables-and-indexes/large-tables`](../../tables-and-indexes/large-tables/README.md)
- [`transactions-and-xid/xid-wraparound-risk`](../../transactions-and-xid/xid-wraparound-risk/README.md)
- [`vacuum-and-autovacuum/autovacuum-not-keeping-up`](../../vacuum-and-autovacuum/autovacuum-not-keeping-up/README.md)
- [`vacuum-and-autovacuum/dead-tuples`](../../vacuum-and-autovacuum/dead-tuples/README.md)
- [`vacuum-and-autovacuum/table-bloat`](../../vacuum-and-autovacuum/table-bloat/README.md)

Start with the workflow whose title most closely matches the symptom you are
investigating; if uncertain, `database-health/comprehensive-health-check`
and `incident-response/production-triage` both provide a broad first pass
that surfaces which specific workflow to open next.
