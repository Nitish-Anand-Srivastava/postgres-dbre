# 04_maintenance_window_checklist

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `04_maintenance_window_checklist.md` |
| Purpose | The checklist itself: the ordered pre-window, go/no-go, in-window, and post-window steps that wrap whichever specific maintenance action is being performed. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Any instance (writer or reader) |
| Safety | DOCUMENTATION -- no SQL executed by this file itself |
| Expected impact | None from this file directly; the wrapped maintenance action carries its own impact, documented in its own workflow. |
| Required privileges | N/A for this file itself; see the specific maintenance action's workflow for its own required privileges. |
| Prerequisites | Full read-only investigation for this workflow completed; maintenance window and second engineer approval obtained. |
| Execution order | Step 04 of workflow `maintenance/planned-maintenance-window-checklist` |
| Related scripts | 01_pre_window_activity_and_transactions.sql, 02_pre_window_lock_and_blocking_check.sql, 03_pre_window_topology_and_replication_check.sql, 05_post_window_verification.sql |

## How to interpret / use this runbook

Work the checklist in order and make the go/no-go decision explicit and attributable -- most maintenance windows that become incidents do so because a pre-window signal was visible and proceeded past, not because the maintenance action itself was wrong.

---

## Before the window (T-minus one day)

1. Confirm the specific maintenance action's own workflow has been read and its steps are written into the change ticket -- this checklist wraps that workflow, it does not replace it.
2. Confirm a recent backup is genuinely restorable, not merely present (`disaster-recovery/backup-and-restore-validation`).
3. Confirm the rollback path is written down and someone has read it. For an engine upgrade the rollback is a restore, which has a real data-loss cost -- that needs to be understood before the window, not discovered during it.
4. Confirm the window is communicated to trading operations, market makers if relevant, and customer support, with a stated expected duration.

## Immediately before the window opens

5. Run `01_pre_window_activity_and_transactions.sql`. Resolve or accept every long-running transaction listed.
6. Run `02_pre_window_lock_and_blocking_check.sql`. Both results must be empty.
7. Run `03_pre_window_topology_and_replication_check.sql`. Confirm the writer is where you expect, readers are low-lag, and no slot is retaining unexpected WAL.
8. Save all three outputs into the change ticket as the pre-window baseline.

## Go / no-go

State the decision explicitly, with a named decision-maker. Any of the following is a no-go by default, overridable only by an explicit, recorded decision:

- A transaction open longer than the planned window duration that nobody owns.
- A blocking chain or DDL lock wait already in progress.
- A reader with elevated lag, or fewer healthy readers than the HA design assumes.
- No verified restorable backup.
- Activity materially above the expected off-peak baseline.

## During the window

9. Execute the specific maintenance action following its own workflow.
10. Keep a running time log. If the planned duration elapses and the change is not complete, escalate and begin the rollback path rather than extending silently.

## After the change, before declaring the window closed

11. Run `05_post_window_verification.sql` and compare against the pre-window baseline: settings should match intent, the writer should be the instance you expect, and connection counts should be recovering toward their normal shape.
12. Run `database-health/post-maintenance-check` for the broader health pass.
13. Confirm the application's own smoke tests pass -- order placement, balance lookup, deposit and withdrawal paths -- not just that the database accepts connections.
14. Watch the first full trading session afterward for plan or latency regressions (`query-optimization/query-regression`).

## Closing out

15. Record in the ticket: actual versus planned duration, anything that deviated from the runbook, and any check that should be added to this checklist next time. The overrun trend across windows is more valuable than any single window's record.
