# Table Access Pattern Analysis

**Category:** Table and Index Health | **Workflow:** `tables-and-indexes/table-access-patterns`

## 1. Problem Description

Characterizes how a table is actually accessed (read-heavy vs write-heavy, sequential vs index-driven, hot vs cold) to inform indexing, partitioning, and caching decisions.

## 2. Typical Symptoms

- Uncertainty about whether a table is a good candidate for a specific optimization (index, partition, cache) without first understanding its actual access pattern.

## 3. Business Impact

- Optimizing a table without understanding its real access pattern risks solving the wrong problem (e.g. adding an index to a write-heavy table with few reads, adding write overhead for no benefit).

## 4. Possible Root Causes

- N/A -- diagnostic/characterization workflow.

## 5. Investigation Strategy

1. Compare read (seq_scan + idx_scan) vs write (n_tup_ins/upd/del) volume.
2. Compare index scan vs sequential scan ratio.
3. Cross-reference with pg_stat_statements for the specific query shapes touching the table.

## 6. Prerequisites

- pg_stat_statements recommended.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_read_write_ratio.sql`](scripts/01_read_write_ratio.sql) -- Compares read activity (scans) against write activity (inserts/updates/deletes) per table.

## 8. Interpretation Guide

- A table with n_tup_upd/n_tup_ins far exceeding idx_scan+seq_scan is write-dominated -- index additions should be weighed carefully against their write-amplification cost. A table with the reverse ratio is read-dominated and a better candidate for additional indexing.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- N/A.

**Short-term remediation** (hours to days):

- Route the finding into the appropriate specific workflow (missing-index-candidates for read-heavy tables needing better index coverage, vacuum-and-autovacuum for write-heavy tables needing more aggressive vacuum tuning).

**Long-term engineering fix** (days to weeks):

- Document known access patterns for the platform's core tables (orders, balances, ledger) as living architecture documentation.

## 10. Production Safety

- Read-only.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- N/A.

## 12. Related Issues

- [missing-index-candidates](../missing-index-candidates/README.md)
- [autovacuum-not-keeping-up](../../vacuum-and-autovacuum/autovacuum-not-keeping-up/README.md)
