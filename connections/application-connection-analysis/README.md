# Application-Level Connection Analysis

**Category:** Connection Management | **Workflow:** `connections/application-connection-analysis`

## 1. Problem Description

Deep-dive into a specific application/service's connection behavior -- pool size, connection lifetime, and query pattern -- when that service is suspected of contributing disproportionately to connection-related issues.

## 2. Typical Symptoms

- A specific service is repeatedly implicated in connection-exhaustion/connection-spikes findings.

## 3. Business Impact

- Understanding one service's specific connection behavior in detail is necessary to fix a recurring, service-specific connection problem rather than repeatedly applying database-wide mitigations.

## 4. Possible Root Causes

- See connection-exhaustion and idle-connections for the general root-cause list; this workflow narrows the investigation to one specific, already-implicated service.

## 5. Investigation Strategy

1. Filter all connection/activity views to the specific application_name.
2. Characterize its connection count, state distribution, and typical query pattern over time.
3. Compare against its documented/expected pool configuration.

## 6. Prerequisites

- The specific application_name/usename already identified as the focus, typically from connection-exhaustion or connection-spikes.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_service_connection_detail.sql`](scripts/01_service_connection_detail.sql) -- Detailed connection/state/query breakdown filtered to a specific application, for deep-dive analysis.

## 8. Interpretation Guide

- Compare the service's actual observed behavior against its own configuration (pool min/max, statement timeout) -- a mismatch (e.g. actual connections far exceeding configured pool max) suggests either multiple unpooled instances or a configuration drift, not a single simple leak.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Coordinate directly with the owning team using the specific evidence gathered here.

**Short-term remediation** (hours to days):

- Fix the specific configuration/code issue identified.

**Long-term engineering fix** (days to weeks):

- Add this service's connection budget to max-connections-planning's living documentation.

## 10. Production Safety

- Read-only.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- The owning team cannot resolve the issue without a broader architecture change (e.g. adopting pooling for the first time) -- escalate to database engineering and that team's leadership jointly.

## 12. Related Issues

- [connection-exhaustion](../connection-exhaustion/README.md)
- [max-connections-planning](../max-connections-planning/README.md)
