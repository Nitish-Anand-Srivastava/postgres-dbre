# Idle Connections

**Category:** Connection Management | **Workflow:** `connections/idle-connections`

## 1. Problem Description

A large number of connections sitting fully idle (not idle-in-transaction, just idle) -- consuming a connection slot and a small amount of backend memory without doing any work, potentially crowding out headroom for active work.

## 2. Typical Symptoms

- High idle_count relative to active_count in connection breakdowns.
- Connection count near max_connections despite low actual query throughput.

## 3. Business Impact

- Idle connections are lower-risk than idle-in-transaction (they hold no locks/snapshots) but still consume a connection slot -- at scale, they can still contribute to exhaustion and represent inefficient pool sizing.

## 4. Possible Root Causes

- A connection pool sized much larger than actual concurrent demand requires.
- A pooler in session mode holding connections open between client requests instead of returning them to a shared pool.
- Application instances that open a connection per long-lived worker/thread regardless of actual utilization.

## 5. Investigation Strategy

1. Break down idle connections by application_name.
2. Compare pool size configuration against observed active concurrency to right-size it.

## 6. Prerequisites

- pg_monitor role membership; visibility into application/pooler pool-size configuration.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_idle_connections_by_application.sql`](scripts/01_idle_connections_by_application.sql) -- Breaks down idle (not idle-in-transaction) connections by application to assess pool sizing.

## 8. Interpretation Guide

- A small, stable number of idle connections per application is normal and healthy (pool warm-up); a very large number relative to peak active concurrency suggests over-provisioned pool sizing.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- None typically required unless contributing to active exhaustion.

**Short-term remediation** (hours to days):

- Right-size pool `min`/`max` settings based on observed peak active concurrency, not a guess.
- Switch a session-mode pooler to transaction-mode pooling if the application does not require session-level state.

**Long-term engineering fix** (days to weeks):

- Document connection budgets per service (see max-connections-planning).

## 10. Production Safety

- Read-only.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- N/A -- typically a low-urgency tuning finding.

## 12. Related Issues

- [connection-pooling](../connection-pooling/README.md)
- [max-connections-planning](../max-connections-planning/README.md)
