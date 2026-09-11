# Reader Instance Performance

**Category:** Replication and High Availability | **Workflow:** `replication-and-ha/reader-performance`

## 1. Problem Description

Investigates performance issues specific to an Aurora reader instance -- distinct from writer performance workflows, since readers have their own independent buffer cache, connection pool, and query load.

## 2. Typical Symptoms

- Read-only queries routed to a reader endpoint are slow, while the writer performs normally.
- One specific reader in a multi-reader cluster underperforms relative to its siblings.

## 3. Business Impact

- Reader performance issues directly degrade any read-heavy, latency-sensitive feature deliberately offloaded to readers (market data display, order history, balance lookups) without necessarily showing up in writer-side monitoring.

## 4. Possible Root Causes

- The reader instance is a smaller instance class than the writer and is undersized for the read traffic routed to it.
- Reader-specific cold cache after a recent reboot/failover-related promotion.
- An uneven query router sending disproportionate traffic to one specific reader.
- Elevated reader lag itself causing query-side waits on recovery conflict resolution.

## 5. Investigation Strategy

1. Confirm which specific reader is affected and its instance class.
2. Check its buffer cache hit ratio and current session/query load directly.
3. Check its replica lag, since very high lag can itself cause query delays.

## 6. Prerequisites

- Direct connection access to the specific reader instance (not just the reader load-balanced endpoint) to isolate a single-reader issue.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_reader_cache_and_load.sql`](scripts/01_reader_cache_and_load.sql) -- Checks buffer cache hit ratio and current session load directly on the specific reader instance.
2. [`scripts/02_reader_lag_check.sql`](scripts/02_reader_lag_check.sql) -- Checks this specific reader's lag via the Aurora-native cluster function.

## 8. Interpretation Guide

- If all readers in the cluster show the issue equally, suspect a cluster-wide cause (write volume, lag) rather than an instance-specific one; if only one reader is affected, suspect instance-specific factors (recent restart, an uneven query router, or a hardware-level AWS issue worth a support case).

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Route traffic away from a specifically underperforming reader if your query router/application supports per-instance routing.

**Short-term remediation** (hours to days):

- Scale the underperforming reader to match the others' instance class if it was provisioned smaller.

**Long-term engineering fix** (days to weeks):

- Ensure the reader fleet is sized and load-balanced appropriately for the read traffic volume (see storage-and-capacity/capacity-forecasting).

## 10. Production Safety

- Investigation scripts are read-only.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- A single reader underperforms with no explainable cause (matching instance class, matching lag, matching query load) -- open an AWS Support case for a possible instance-level hardware issue.

## 12. Related Issues

- [replication-lag](../replication-lag/README.md)
- [writer-reader-imbalance](../writer-reader-imbalance/README.md)
