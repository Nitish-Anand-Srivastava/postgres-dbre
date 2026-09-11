# max_connections Capacity Planning

**Category:** Connection Management | **Workflow:** `connections/max-connections-planning`

## 1. Problem Description

Proactive capacity planning workflow for establishing an appropriate max_connections budget and per-service connection allocation, rather than reacting to exhaustion after the fact.

## 2. Typical Symptoms

- No active symptom -- proactive planning workflow, typically run during capacity reviews or before onboarding a new service.

## 3. Business Impact

- A documented, deliberately planned connection budget prevents the class of incident covered by connection-exhaustion from recurring as the platform adds more services.

## 4. Possible Root Causes

- N/A -- planning workflow.

## 5. Investigation Strategy

1. Establish current total connection budget (max_connections minus reserved).
2. Inventory current per-service allocation.
3. Compare against each service's actual peak observed usage to find both over- and under-provisioned services.

## 6. Prerequisites

- pg_monitor role membership; inventory of all services connecting to the database.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_current_budget_and_allocation.sql`](scripts/01_current_budget_and_allocation.sql) -- Establishes current max_connections budget and per-application actual usage as the planning baseline.

## 8. Interpretation Guide

- The sum of all services' pool `max` settings should never exceed a safe fraction (commonly 70-80%) of max_connections, leaving explicit headroom for migrations, monitoring tools, and burst capacity.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- N/A.

**Short-term remediation** (hours to days):

- Right-size any service found significantly over- or under-provisioned relative to its actual observed peak usage.

**Long-term engineering fix** (days to weeks):

- Maintain a living connection-budget document reviewed whenever a new service is onboarded or Aurora instance class changes (which changes the effective max_connections ceiling).

## 10. Production Safety

- Read-only.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Planned service growth would exceed available connection budget even after pooling -- escalate for an instance-class or architecture decision (e.g. mandatory pooling for all new services) ahead of actually hitting exhaustion.

## 12. Related Issues

- [connection-exhaustion](../connection-exhaustion/README.md)
- [connection-pooling](../connection-pooling/README.md)
