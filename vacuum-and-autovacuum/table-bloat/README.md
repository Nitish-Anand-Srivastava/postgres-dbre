# Table Bloat

**Category:** Vacuum and Autovacuum | **Workflow:** `vacuum-and-autovacuum/table-bloat`

## 1. Problem Description

Investigates physical table bloat -- disk space consumed by dead/reusable tuple space that has not been returned to the OS or reused efficiently, distinct from the logical dead-tuple count itself.

## 2. Typical Symptoms

- Table on-disk size much larger than expected for its live row count.
- Growing total_relation_size with flat or declining n_live_tup.

## 3. Business Impact

- Bloat increases storage costs and, more importantly, increases the number of pages that must be read for a sequential or even index scan, directly degrading query performance.

## 4. Possible Root Causes

- Sustained dead-tuple accumulation (see dead-tuples) without full space reclamation, since ordinary VACUUM marks space reusable but does not necessarily shrink the file on disk.
- A historical spike in deletes/updates (e.g. a large one-time cleanup) leaving behind free space that is reused slowly.

## 5. Investigation Strategy

1. Estimate bloat using the catalog-only proxy (safe, no lock, approximate).
2. Confirm with pgstattuple's exact physical scan for the top candidates (heavier, but precise).
3. Decide between routine VACUUM (reclaims space for reuse, does not shrink file) and a maintenance-window VACUUM FULL/pg_repack (shrinks file, but locks/rewrites).

## 6. Prerequisites

- pgstattuple extension for the exact-bloat script (optional but recommended for confirmation).

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_bloat_estimate_catalog_only.sql`](scripts/01_bloat_estimate_catalog_only.sql) -- Lightweight, lock-free bloat proxy using only pg_class/pg_stat_all_tables -- always safe to run.
2. [`scripts/02_exact_bloat_pgstattuple.sql`](scripts/02_exact_bloat_pgstattuple.sql) -- Exact physical bloat scan for one specific table using the pgstattuple extension.

## 8. Interpretation Guide

- Regular (non-FULL) VACUUM makes dead space available for reuse by future inserts/updates on the same table -- it does NOT shrink the file on disk. Only VACUUM FULL, CLUSTER, or pg_repack physically shrink the table, and all require careful scheduling due to locking.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- None -- bloat remediation is inherently a planned, scheduled action, not an emergency one, unless bloat is actively causing a severe performance incident.

**Short-term remediation** (hours to days):

- Ensure routine VACUUM is keeping bloat from growing further (see autovacuum-not-keeping-up) before considering a space-reclaiming operation.

**Long-term engineering fix** (days to weeks):

- Schedule a VACUUM FULL (small tables, brief maintenance window) or pg_repack (installed via Aurora's supported extension list, minimal-lock alternative for large tables) during a planned maintenance window -- see maintenance/ for the runbook and locking implications.

## 10. Production Safety

- Bloat estimation scripts are read-only and safe at any time.
- pgstattuple's exact scan takes a light read lock and can be I/O-intensive on very large tables -- prefer pgstattuple_approx() for tables over a few GB, or schedule the exact scan off-peak.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Bloat is confirmed severe (free_pct from pgstattuple well above 30-40%) on a business-critical table -- escalate to schedule a maintenance-window remediation with stakeholder sign-off.

## 12. Related Issues

- [dead-tuples](../dead-tuples/README.md)
- [index-bloat](../index-bloat/README.md)
- [maintenance](../../maintenance/README.md)
