# Emergency / Anti-Wraparound Autovacuum

**Category:** Vacuum and Autovacuum | **Workflow:** `vacuum-and-autovacuum/emergency-autovacuum`

## 1. Problem Description

A table has crossed autovacuum_freeze_max_age and is now being vacuumed in mandatory 'anti-wraparound' mode (or has crossed vacuum_failsafe_age and is in accelerated failsafe mode), which cannot be cancelled without directly increasing wraparound risk.

## 2. Typical Symptoms

- Autovacuum log entries explicitly marked '(to prevent wraparound)'.
- A vacuum that appears to ignore normal cost-based throttling and run at maximum speed (failsafe mode, PostgreSQL 14+).
- pg_stat_progress_vacuum showing a worker on a table whose age already exceeds autovacuum_freeze_max_age.

## 3. Business Impact

- This is the last automatic safety net before a full wraparound-protection outage -- it is expected, necessary behavior, and interfering with it (e.g. cancelling it) directly increases outage risk.

## 4. Possible Root Causes

- See transactions-and-xid/xid-wraparound-risk for the full root-cause list; this workflow is specifically about safely handling the emergency vacuum once it has already started.

## 5. Investigation Strategy

1. Confirm the vacuum is genuinely in anti-wraparound/failsafe mode (not just a normal, but slow, routine vacuum).
2. Monitor its progress rather than attempting to stop it.
3. Ensure no long-running transaction is preventing it from completing.

## 6. Prerequisites

- pg_monitor role membership; rds_superuser-equivalent only if manual intervention beyond monitoring becomes necessary.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_confirm_emergency_vacuum.sql`](scripts/01_confirm_emergency_vacuum.sql) -- Confirms whether a currently running vacuum is in anti-wraparound/failsafe mode by cross-referencing its target table's age against the configured thresholds.
2. [`scripts/02_safe_handling_during_emergency_vacuum.md`](scripts/02_safe_handling_during_emergency_vacuum.md) -- Manual guidance for what to do (and not do) while an anti-wraparound/failsafe vacuum is in progress.

## 8. Interpretation Guide

- In failsafe mode, PostgreSQL suspends cost-based delay entirely and may skip index cleanup to freeze rows as fast as possible -- this is intentional and appropriate given the alternative (a full outage), even though it consumes more I/O/CPU than a routine vacuum.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Do NOT cancel or terminate an anti-wraparound/failsafe vacuum. Instead, ensure it can complete: resolve any long-running transaction that could still be blocking its progress.

**Short-term remediation** (hours to days):

- Once complete, immediately address the underlying root cause (see xid-wraparound-risk) so this does not recur within days.

**Long-term engineering fix** (days to weeks):

- Tune autovacuum settings proactively so freeze work happens in smaller, routine increments well before failsafe mode is ever triggered again.

## 10. Production Safety

- This vacuum itself is the safety mechanism -- the primary safety guidance here is 'do not interfere with it', not 'here is a destructive action to avoid'.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- The database has already begun refusing new transactions (full wraparound outage) -- this is beyond routine emergency-autovacuum monitoring; escalate as a major incident immediately.

## 12. Related Issues

- [xid-wraparound-risk](../../transactions-and-xid/xid-wraparound-risk/README.md)
- [autovacuum-not-keeping-up](../autovacuum-not-keeping-up/README.md)
