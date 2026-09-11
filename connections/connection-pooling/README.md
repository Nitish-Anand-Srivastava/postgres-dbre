# Connection Pooling (PgBouncer) Considerations

**Category:** Connection Management | **Workflow:** `connections/connection-pooling`

## 1. Problem Description

Guidance and database-side diagnostics for environments using PgBouncer (or an equivalent external pooler) in front of Aurora PostgreSQL, clearly separating what is visible/actionable from the PostgreSQL side vs. what must be investigated on the pooler itself.

## 2. Typical Symptoms

- Application-visible connection errors that do not correlate with the database's own max_connections utilization -- often a sign the bottleneck is the pooler layer, not PostgreSQL.

## 3. Business Impact

- A correctly configured pooler is essential infrastructure for a high-connection-concurrency exchange workload; pooler misconfiguration is a very common source of connection-related incidents that are misdiagnosed as database problems.

## 4. Possible Root Causes

- Pooler pool_size too small for actual concurrency needs.
- Pooler in session mode instead of transaction mode, multiplying effective connection consumption.
- Pooler itself under CPU/memory pressure (a separate host/process from the database entirely).

## 5. Investigation Strategy

1. From the database side: confirm how many connections the pooler itself is actually using against max_connections (should be a small, stable number in transaction-pooling mode).
2. From the pooler side (not a PostgreSQL SQL concern): check PgBouncer's own SHOW POOLS / SHOW STATS admin console for pooler-side queue depth and wait times.

## 6. Prerequisites

- Administrative access to the PgBouncer instance's admin console for pooler-side diagnostics (outside the scope of PostgreSQL SQL entirely).

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_pooler_connection_footprint.sql`](scripts/01_pooler_connection_footprint.sql) -- Checks how many database-side connections the pooler's application_name/user is actually consuming, to distinguish a database-side vs. pooler-side bottleneck.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Aurora does not provide a managed PgBouncer -- pooling is an application/infrastructure-team responsibility layered in front of the Aurora endpoint(s), typically run on separate EC2/ECS/Fargate infrastructure or as a sidecar.

## 8. Interpretation Guide

- If the database shows ample max_connections headroom while the application experiences connection errors/timeouts, the problem is almost certainly on the pooler side (or between the application and the pooler), not in PostgreSQL -- do not keep searching PostgreSQL-side catalogs for a pooler-side problem.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Increase PgBouncer pool_size (pooler-side config, not a PostgreSQL change) if pooler-side queuing is confirmed.

**Short-term remediation** (hours to days):

- Move from session to transaction pooling mode if application compatibility allows (no session-level SET/temp tables/prepared statements relied upon across statements).

**Long-term engineering fix** (days to weeks):

- Document the intended pooler architecture (per-service PgBouncer vs. shared, pool_size per service) as part of max-connections-planning.

## 10. Production Safety

- Database-side diagnostics here are read-only; pooler-side changes are outside PostgreSQL's safety model entirely and follow the pooler's own operational practices.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Pooler-side issues are outside DBA/PostgreSQL scope in many organizations -- escalate to the team owning the pooler infrastructure if the database side is confirmed healthy.

## 12. Related Issues

- [connection-exhaustion](../connection-exhaustion/README.md)
- [max-connections-planning](../max-connections-planning/README.md)
