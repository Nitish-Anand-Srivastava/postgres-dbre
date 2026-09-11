# Connection Exhaustion -- First Response Checklist

**Category:** Incident Response | **Workflow:** `incident-response/connection-exhaustion`

## 1. Problem Description

New connections are being refused with `FATAL: sorry, too many clients already` while existing sessions continue to work. This is the rapid triage version: find out who is holding the slots, reclaim enough of them to restore service, and identify the owning service so the slots do not simply refill. The structural work of pool sizing and connection budgeting belongs in `connections/connection-exhaustion`.

## 2. Typical Symptoms

- `FATAL: sorry, too many clients already` in application logs, or `remaining connection slots are reserved for roles with the SUPERUSER attribute`.
- New pods or services failing their startup health checks while already-running instances stay healthy.
- DatabaseConnections in CloudWatch flat-lining at a ceiling rather than fluctuating with traffic.
- Operators unable to open a psql session to investigate, because the slots are gone.
- A service that was just deployed or restarted unable to connect, while the fleet it replaced was fine.

## 3. Business Impact

- Any service that needs a NEW connection fails completely: newly started pods, scheduled settlement jobs, and reconciliation runs -- even though the database is healthy and fast for everyone already connected.
- Withdrawal and deposit processors that connect on demand rather than holding a pool are typically the first to fail, which directly affects customer funds movement.
- Responders lose their own access, which is why a reserved break-glass path matters more here than in any other incident type.

## 4. Possible Root Causes

- A service deployed with a pool size that, multiplied by its replica count, exceeds the cluster's entire connection budget.
- A connection leak: sessions opened and never returned to the pool, visible as a steadily climbing idle count that never falls.
- Idle-in-transaction sessions holding slots (and snapshots, and locks) because the application failed to commit or roll back after an exception.
- A pooler misconfigured into session mode where transaction mode was intended, so multiplexing never happens.
- A deployment rollout that doubles connections briefly while old and new replicas overlap.
- A slowdown elsewhere in the database: each request holds its connection longer, so the same request rate needs far more concurrent connections.
- Batch or analytics tooling opening one connection per worker thread against the writer.

## 5. Investigation Strategy

1. Confirm the ceiling and how close to it you are -- this takes one query and turns a vague report into a measured fact.
2. Break the connections down by state, because idle, idle-in-transaction and active slots each have a different owner and a different fix.
3. Attribute the slots to a service via application_name and user, so you know who to call while you are still reclaiming.
4. List the long-idle sessions, which are the cheapest and safest slots to reclaim.
5. List the idle-in-transaction sessions separately, which are more valuable to reclaim but carry rollback consequences.
6. Reclaim carefully and in parallel with the owning service reducing its pool, then verify headroom has genuinely recovered.

## 6. Prerequisites

- `pg_monitor` role membership, plus `pg_signal_backend` (or `rds_superuser`) for any reclaim action.
- A break-glass connection path that is not subject to the same exhaustion -- superuser_reserved_connections exists precisely for this and should be verified before you need it.
- A contact path to each service that appears in application_name, because reclaiming slots without reducing demand is a temporary fix at best.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_connection_headroom.sql`](scripts/01_connection_headroom.sql) -- Measures how close the instance is to its connection ceiling, including the reserved superuser slots.
2. [`scripts/02_connections_by_state.sql`](scripts/02_connections_by_state.sql) -- Breaks the connections down by state, which determines both who owns them and how safely they can be reclaimed.
3. [`scripts/03_connections_by_application.sql`](scripts/03_connections_by_application.sql) -- Attributes the connections to a service and user so the owning team can be contacted while reclaim is still in progress.
4. [`scripts/04_long_idle_sessions.sql`](scripts/04_long_idle_sessions.sql) -- Lists plain idle sessions ranked by idle duration -- the cheapest and safest slots to reclaim.
5. [`scripts/05_idle_in_transaction_sessions.sql`](scripts/05_idle_in_transaction_sessions.sql) -- Lists sessions holding an open transaction while idle -- slots that are also damaging vacuum and concurrency.
6. [`scripts/06_reclaim_connection_slots.md`](scripts/06_reclaim_connection_slots.md) -- Guarded runbook for reclaiming connection slots safely and for applying a per-role connection limit so they do not immediately refill.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Aurora derives max_connections from the instance class's memory through the parameter-group formula, so raising it is a parameter-group change (and usually a restart), not a live mitigation -- plan the budget around the instance class instead.
- RDS Proxy holds its own pool of database connections and multiplexes application connections onto them; when a proxy is in the path, the connection count the database sees is the proxy's, and the real leak may be between the application and the proxy rather than between the proxy and the database.
- Aurora reader instances have their own independent connection ceilings, so read traffic that is correctly routed to readers does not consume writer slots -- and misrouted read traffic is a common, easily fixed cause of writer exhaustion.

## 8. Interpretation Guide

- pct_utilized above roughly 95% is the actionable threshold: superuser_reserved_connections means the last few slots are already unavailable to application roles.
- A dominant 'idle' population means a pool is holding far more connections than it uses -- the cheapest possible reclaim, and a pool-sizing conversation.
- A dominant 'idle in transaction' population means an application bug: those sessions also hold snapshots and possibly locks, so they are hurting vacuum and concurrency as well as connection availability.
- A dominant 'active' population means the database is slow rather than leaked-into: each request holds its slot longer, so fix the slowness and the connection count falls by itself.
- One application_name holding a disproportionate share names the owning team immediately, which is usually the fastest path to a durable fix.
- Connection ages clustered within the last few minutes point at a deployment or a restart storm; ages spanning days point at a leak.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Reclaim long-idle sessions one pid at a time per the runbook, starting with the largest offender by application_name.
- Ask the owning service to reduce its pool size or scale in replicas in the same minute -- without that, reclaimed slots refill within seconds.
- Terminate idle-in-transaction sessions that are also blocking others, after confirming the rollback is safe for that transaction.
- If the underlying cause is database slowness rather than leakage, stop reclaiming and switch to the latency or lock-storm workflow instead.

**Short-term remediation** (hours to days):

- Apply a per-role connection limit so no single service can consume the whole budget again: this is a documented, revertible configuration change, not an emergency action.
- Set `idle_in_transaction_session_timeout` for application roles so PostgreSQL reclaims leaked transaction slots automatically.
- Move the highest-churn services behind a transaction-mode pooler.

**Long-term engineering fix** (days to weeks):

- Publish a connection budget per service that sums to comfortably less than max_connections, and enforce it in deployment manifests rather than in a wiki page.
- Alert on connection utilization at 70% and 85%, so exhaustion is a scheduled conversation rather than a page.
- Standardize pool configuration across services so the per-replica connection count is a reviewed value rather than a framework default copied between repositories.

## 10. Production Safety

- Scripts 01-05 are read-only and safe to run during exhaustion, provided you can still get a connection at all -- this is exactly what the reserved superuser slots are for.
- Script 06 ends other sessions and changes role-level limits; read it fully before executing anything.
- Never terminate every matching session in a single set-returning statement. Simultaneous mass reconnection is its own outage, and it is entirely avoidable.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- You cannot obtain a connection at all, even through the reserved break-glass path -- escalate to AWS support immediately.
- Slots refill to the ceiling within seconds of every reclaim and the owning service cannot or will not reduce its pool -- escalate to that service's leadership; this is now an organizational decision, not a database one.
- The exhaustion is a symptom of database slowness rather than leakage, and the slowness is unresolved -- escalate on the latency track instead.
- Withdrawal or settlement processors have been unable to connect for more than a few minutes -- escalate to treasury and compliance in parallel.

## 12. Related Issues

- [production-triage](../production-triage/README.md)
- [database-unavailable](../database-unavailable/README.md)
- [application-timeouts](../application-timeouts/README.md)
- [connection-exhaustion](../../connections/connection-exhaustion/README.md)
- [blocked-queries](../../concurrency-and-locking/blocked-queries/README.md)
