# Sudden Performance Degradation

**Category:** Performance Issues | **Workflow:** `performance/sudden-performance-degradation`

## 1. Problem Description

Performance across the database (or a major subset of workload) degraded abruptly, within seconds to minutes, rather than gradually. This workflow is optimized for rapid correlation against a specific point in time (a deploy, a failover, a maintenance action, a traffic spike) rather than open-ended root-cause exploration.

## 2. Typical Symptoms

- A step-change in latency/error rate visible on dashboards at a specific timestamp.
- Alerting fired within seconds/minutes of a change window, deployment, or known external event (e.g. a market volatility spike).

## 3. Business Impact

- Sudden degradation is the highest-urgency performance scenario -- it typically indicates an active incident in progress rather than a slow-building trend, and requires immediate triage.

## 4. Possible Root Causes

- A deployment introduced a new query pattern, removed/changed an index, or changed connection pool configuration.
- A failover occurred, and the new writer/reader has a cold buffer cache (see performance-after-failover).
- A sudden traffic spike (market volatility) exceeded provisioned capacity.
- A long-running transaction or lock was acquired and is now blocking a wide swath of subsequent queries.
- An autovacuum-related emergency (anti-wraparound vacuum) began consuming significant resources.
- An external dependency (AWS infrastructure event, network partition) degraded connectivity/latency.

## 5. Investigation Strategy

1. Immediately capture current session/lock/wait state before it changes further -- this is the most valuable forensic evidence for a transient issue.
2. Check for a single dominant blocking session or runaway query that could explain a sudden, sharp change.
3. Check whether a deployment or maintenance action occurred in the minutes immediately preceding the degradation.
4. Check whether a failover occurred (compare current writer identity against expected).
5. Check whether an anti-wraparound/emergency autovacuum has started.
6. If nothing above explains it, capture a full production-triage snapshot for handoff/escalation.

## 6. Prerequisites

- Access to deployment/change logs to correlate timestamps.
- AWS Console access to check recent Aurora events (failovers, parameter group changes, maintenance).

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_snapshot_current_state.sql`](scripts/01_snapshot_current_state.sql) -- Captures a broad current-state snapshot (sessions, states, wait events) as the first forensic step.
2. [`scripts/02_dominant_blocking_chain.sql`](scripts/02_dominant_blocking_chain.sql) -- Identifies the single most impactful blocking session, if one exists, to prioritize the fastest possible fix.
3. [`scripts/03_recovery_role_check.sql`](scripts/03_recovery_role_check.sql) -- Confirms whether this instance is currently the writer or a reader, to detect an unnoticed failover.
4. [`scripts/04_autovacuum_emergency_check.sql`](scripts/04_autovacuum_emergency_check.sql) -- Checks for an anti-wraparound or failsafe autovacuum currently running, which can consume significant resources and cannot be safely cancelled.
5. [`scripts/05_recent_wal_and_checkpoint_spike.sql`](scripts/05_recent_wal_and_checkpoint_spike.sql) -- Checks for a recent spike in WAL generation or forced checkpoints that could correlate with the incident window.

## 8. Interpretation Guide

- A single session at the head of a long blocking chain is the highest-priority, fastest-to-fix finding -- resolve it before investigating anything else.
- If a failover timestamp aligns with the degradation onset, treat this as performance-after-failover (cold cache) rather than continuing generic investigation.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Resolve the identified blocking session per concurrency-and-locking/blocked-queries if one is found.
- If correlated with a deploy, coordinate an immediate rollback with the deploying team rather than attempting a forward-fix under incident pressure.

**Short-term remediation** (hours to days):

- Apply the specific remediation from whichever specialized workflow (locking, vacuum, replication, deployment) the correlation points to.

**Long-term engineering fix** (days to weeks):

- Add automated pre/post-deployment health checks (database-health/pre-deployment-check, post-deployment-check) to catch regressions before they reach this severity.

## 10. Production Safety

- All investigation scripts are read-only and safe to run under incident pressure.
- Do not attempt speculative DDL/config changes mid-incident; gather evidence first per this workflow, then act on a specific, confirmed root cause.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- No root cause identified within 10-15 minutes of investigation -- escalate to database engineering leadership and open the full incident-response/production-triage checklist in parallel.

## 12. Related Issues

- [performance-after-deployment](../performance-after-deployment/README.md)
- [performance-after-failover](../performance-after-failover/README.md)
- [production-triage](../../incident-response/production-triage/README.md)
