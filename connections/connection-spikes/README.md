# Connection Spikes

**Category:** Connection Management | **Workflow:** `connections/connection-spikes`

## 1. Problem Description

A sudden, sharp increase in connection count over a short period, whether or not it reaches full exhaustion -- often a leading indicator of exhaustion or of a reconnect storm.

## 2. Typical Symptoms

- Connection count chart showing a sharp step-change rather than gradual growth.
- Correlates with a deployment, a failover, or an upstream outage causing widespread client reconnects.

## 3. Business Impact

- Connection spikes stress both the database (context switching, memory) and any pooler in front of it, and frequently precede a connection-exhaustion incident if not addressed.

## 4. Possible Root Causes

- A deployment restarting many application instances simultaneously, each re-establishing its full connection pool at once.
- A failover triggering a synchronized reconnect storm across all connected clients.
- An upstream dependency outage causing widespread client-side retries that each open a new connection instead of reusing an existing one.

## 5. Investigation Strategy

1. Confirm the spike's timing against known events (deploys, failovers).
2. Break down the spike by application_name to identify the source.
3. Check whether reconnecting clients are using appropriate backoff/jitter.

## 6. Prerequisites

- pg_monitor role membership; deployment/event timeline for correlation.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_connection_state_snapshot.sql`](scripts/01_connection_state_snapshot.sql) -- Snapshots current connection counts by state as the starting point for spike investigation.
2. [`scripts/02_connections_by_application.sql`](scripts/02_connections_by_application.sql) -- Attributes the spike to a specific application/service.

## 8. Interpretation Guide

- A spike that resolves on its own within seconds to a couple of minutes and correlates with a known event (deploy/failover) is expected and low-risk; a spike that persists or continues climbing needs active investigation as a potential leak or retry storm.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If the spike is actively risking exhaustion, apply connection-exhaustion's immediate remediation.

**Short-term remediation** (hours to days):

- Stagger application instance restarts/deploys (rolling restarts) instead of all-at-once to smooth reconnection load.

**Long-term engineering fix** (days to weeks):

- Ensure all client-side reconnect logic uses randomized backoff/jitter to avoid synchronized reconnect storms.

## 10. Production Safety

- Read-only.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Spike does not correlate with any known event and continues growing -- escalate as a potential leak/incident.

## 12. Related Issues

- [connection-exhaustion](../connection-exhaustion/README.md)
- [performance-after-failover](../../performance/performance-after-failover/README.md)
