# 05_post_upgrade_validation_runbook

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `05_post_upgrade_validation_runbook.md` |
| Purpose | Guarded runbook for the database-side work an engine upgrade does not do for you: extension updates, planner statistics refresh, and post-upgrade validation. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only (the query reads/writes state that only exists or is meaningful on the writer) |
| Safety | LOW RISK WRITE (ANALYZE and ALTER EXTENSION ... UPDATE; SHARE UPDATE EXCLUSIVE locks only, no table rewrite -- see runbook before running any step) |
| Expected impact | Real I/O and CPU for the duration of each ANALYZE; a brief lock on extension-owned objects during ALTER EXTENSION ... UPDATE; pg_stat_statements_reset() permanently discards accumulated query statistics. |
| Required privileges | Table owner, or a role granted the `MAINTAIN` privilege on the table (PostgreSQL 16+), or a role with `pg_maintain` membership. DDL variants additionally require the privileges needed for the specific DDL statement (e.g. ownership to ALTER TABLE). |
| Prerequisites | Full read-only investigation for this workflow completed; maintenance window and second engineer approval obtained. |
| Execution order | Step 05 of workflow `maintenance/minor-version-upgrade-readiness` |
| Related scripts | 01_current_engine_version_inventory.sql, 03_extension_and_settings_upgrade_surface.sql, ../statistics-maintenance/README.md |

## How to interpret / use this runbook

Work through the numbered steps in order after the cluster is accepting connections again; the statistics refresh in step 2 is the step most often skipped and the one most often responsible for a post-upgrade performance incident.

---

An engine upgrade does not refresh planner statistics and does not update installed extensions. Both are real database operations and belong here rather than in an auto-running script.

## 1. Confirm the upgrade actually applied

Re-run `01_current_engine_version_inventory.sql` and compare against the pre-upgrade output in the change ticket. Re-run `03_extension_and_settings_upgrade_surface.sql` and diff the key settings against the pre-upgrade baseline -- an unexplained default change is a finding to chase now, not after it causes a regression.

## 2. Refresh planner statistics

Statistics survive a minor version upgrade, but a planner change meeting stale statistics is the single most common cause of a post-upgrade plan regression. Refresh the busiest tables first, one at a time, watching load between each:

```sql
ANALYZE VERBOSE public.orders;
ANALYZE VERBOSE public.trades;
ANALYZE VERBOSE public.ledger_entries;
```

Replace these with the actual hot tables on this cluster (rank them with `maintenance/statistics-maintenance` script 01). `ANALYZE` takes only a SHARE UPDATE EXCLUSIVE lock, so ordinary reads and writes continue -- but it is real I/O, so sequence it rather than launching it across every table at once on a cluster still absorbing reconnect traffic.

A whole-database `ANALYZE;` is acceptable on a small cluster and a poor idea on a large one during a reconnect storm; prefer the ranked, table-at-a-time form here.

## 3. Update extensions that moved forward

Compare script 03's post-upgrade output against the pre-upgrade baseline. Where an extension has a newer default_version available, follow `maintenance/extension-upgrade-planning` -- its runbook covers classifying the version jump before applying:

```sql
ALTER EXTENSION pg_stat_statements UPDATE;
```

## 4. Reset query statistics for a clean post-upgrade baseline

Where `pg_stat_statements` is installed, the pre-upgrade accumulated statistics mix old-planner and new-planner executions, which makes a post-upgrade regression hunt harder, not easier. Resetting gives a clean comparison baseline -- but it also discards history that other investigations may still need, so agree the trade-off before running it:

```sql
SELECT pg_stat_statements_reset();
```

## 5. Validate before declaring the window closed

1. Run `database-health/post-maintenance-check`.
2. Run `maintenance/planned-maintenance-window-checklist` script 05 for the post-window verification queries.
3. Watch the top queries by mean time for the first full trading session after the upgrade (`query-optimization/query-regression`) -- a regression that only appears under real order-book load will not show up in a smoke test.

## Rollback position

There is no in-place downgrade for an engine version. The rollback path is a restore (snapshot or point-in-time) to just before the upgrade, which loses everything committed since -- which is exactly why the backup verification step in script 04's pre-window checklist is not optional. For a blue/green upgrade, the blue environment remains available until you delete it, which is a materially better rollback position and another argument for that option.
