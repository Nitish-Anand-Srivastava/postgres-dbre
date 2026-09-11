# Vacuum Progress Monitoring

**Category:** Vacuum and Autovacuum | **Workflow:** `vacuum-and-autovacuum/vacuum-progress`

## 1. Problem Description

Tracks the real-time progress of an in-flight VACUUM (manual or autovacuum) operation, to answer 'how much longer will this take' and 'is it stuck'.

## 2. Typical Symptoms

- A known VACUUM is running and its completion time/impact needs to be estimated.
- Uncertainty about whether a long-running vacuum is stuck or genuinely making progress.

## 3. Business Impact

- Understanding vacuum progress lets the DBA make an informed decision about whether to let it continue, especially when the vacuum itself is competing for I/O with production traffic.

## 4. Possible Root Causes

- N/A -- this is a monitoring workflow for an already-running vacuum, not a root-cause investigation.

## 5. Investigation Strategy

1. Query pg_stat_progress_vacuum for the specific relation.
2. Interpret phase and the PG17 byte-based dead-tuple counters to estimate remaining work.
3. Re-run periodically to confirm heap_blks_scanned is advancing (not stalled).

## 6. Prerequisites

- pg_monitor role membership.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_vacuum_progress_detail.sql`](scripts/01_vacuum_progress_detail.sql) -- Shows detailed progress for every currently running VACUUM (manual or autovacuum), using PostgreSQL 17's byte-based progress columns.
2. [`scripts/02_relation_scan_rate.sql`](scripts/02_relation_scan_rate.sql) -- Computes the target table's total size against the vacuum's current scanned-block progress to estimate percent complete.

## 8. Interpretation Guide

- heap_blks_scanned advancing between two snapshots confirms the vacuum is making progress, even if slowly. A phase stuck at 'vacuuming indexes' for a long time on a table with many/large indexes is expected, not necessarily stuck.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- None required if progressing normally; if genuinely stalled (heap_blks_scanned not advancing across several checks and no visible wait_event explaining why), investigate for an internal lock conflict.

**Short-term remediation** (hours to days):

- Consider `VACUUM (PARALLEL n)` behavior is automatic for index vacuuming when the table has multiple indexes and maintenance_work_mem permits -- no manual action normally needed.

**Long-term engineering fix** (days to weeks):

- If vacuum on this table routinely takes an inconvenient amount of time, investigate whether it is a partitioning candidate.

## 10. Production Safety

- All scripts are read-only. VACUUM itself (non-FULL) does not block reads/writes to the table it targets, aside from momentary lock acquisition for truncation at the very end (which can itself be skipped with `VACUUM (TRUNCATE false)` if that final step is a concern).

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- A vacuum has been running for an unusually long time with no progress and no clear cause -- escalate to database engineering.

## 12. Related Issues

- [autovacuum-not-keeping-up](../autovacuum-not-keeping-up/README.md)
- [emergency-autovacuum](../emergency-autovacuum/README.md)
