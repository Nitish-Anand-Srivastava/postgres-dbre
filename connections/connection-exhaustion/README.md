# Connection Exhaustion

**Category:** Connection Management | **Workflow:** `connections/connection-exhaustion`

## 1. Problem Description

The database is at or near max_connections, causing new connection attempts to be rejected outright -- a full application-facing outage for any service unable to obtain a connection.

## 2. Typical Symptoms

- Application errors: 'FATAL: too many connections for role/database' or 'sorry, too many clients already'.
- Connection count in pg_stat_activity at or very near max_connections.

## 3. Business Impact

- Connection exhaustion is a hard outage for any new request needing a database connection -- existing connections continue to work, but no new work can start, which for a trading platform means new orders/logins fail outright.

## 4. Possible Root Causes

- A connection leak in an application/service (connections opened but never returned to the pool).
- A pool misconfiguration deploying far more application instances/pool-size than the database's max_connections budget.
- A sudden burst of legitimate demand (traffic spike, market volatility) exceeding provisioned capacity.
- No connection pooler in front of the database at all, with each application instance connecting directly.

## 5. Investigation Strategy

1. Confirm current utilization against max_connections.
2. Break down connections by application_name/usename to find the specific source.
3. Check for a large number of idle connections (potential leak/pool misconfiguration) vs. active connections (genuine demand).

## 6. Prerequisites

- pg_monitor role membership.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_connection_headroom.sql`](scripts/01_connection_headroom.sql) -- Checks current connection utilization against max_connections.
2. [`scripts/02_connections_by_application.sql`](scripts/02_connections_by_application.sql) -- Breaks connections down by application_name/usename/state to identify the source.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- On Aurora, max_connections is typically derived automatically from the instance class's memory via a parameter-group formula rather than freely configurable -- increasing it substantially usually means moving to a larger instance class, not just editing a parameter.

## 8. Interpretation Guide

- A large idle_count relative to active_count for a specific application_name points to a leak or an oversized/misconfigured pool holding connections unnecessarily -- distinct from genuine demand, which shows up as a high active_count.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If a specific application/service is clearly leaking connections, restart it to release them as an immediate mitigation while the underlying bug is fixed.
- If genuinely legitimate demand has exceeded capacity, and Aurora max_connections headroom exists at a larger instance class, consider an emergency vertical scale.

**Short-term remediation** (hours to days):

- Introduce or right-size a connection pooler (PgBouncer) in front of the database to multiplex many application connections onto fewer database connections.
- Fix the specific application-side leak (missing connection.close()/context-manager usage).

**Long-term engineering fix** (days to weeks):

- Establish a documented per-service connection budget (see max-connections-planning) so total planned connections never approach max_connections under normal peak conditions.

## 10. Production Safety

- All investigation scripts are read-only.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- The root cause is an application bug causing a leak -- escalate to the owning team immediately, since restarting the service is only a temporary mitigation.

## 12. Related Issues

- [connection-pooling](../connection-pooling/README.md)
- [max-connections-planning](../max-connections-planning/README.md)
- [connection-contention](../../concurrency-and-locking/connection-contention/README.md)
