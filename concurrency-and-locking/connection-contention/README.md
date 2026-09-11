# Connection-Level Contention

**Category:** Locking and Concurrency | **Workflow:** `concurrency-and-locking/connection-contention`

## 1. Problem Description

Sessions are waiting not on table/row locks but on connection-level or client-level resources -- for example, waiting for a connection pool slot, or waiting on Client wait events indicating the server is ready but the client/network side is slow to proceed.

## 2. Typical Symptoms

- High Client or IPC wait_event_type share in current load.
- Application-side connection pool exhaustion errors even though the database's own max_connections has headroom.
- Sessions sitting in 'active' state for long periods with wait_event = 'ClientRead' (server waiting for the client to send the next command).

## 3. Business Impact

- Connection-level contention often indicates the bottleneck is actually in the application/pooler layer, not the database -- misdiagnosing it as a database problem wastes response time and can lead to ineffective database-side remediation.

## 4. Possible Root Causes

- Application connection pool sized far below actual concurrency needs, causing queuing before a connection even reaches the database.
- A pooler (PgBouncer) in session mode holding connections open across idle periods far longer than necessary, starving the pool.
- Network latency/instability between application and database causing sessions to sit in ClientRead longer than expected.
- An application holding a connection open while performing a slow non-database operation (an external API call) mid-transaction.

## 5. Investigation Strategy

1. Break down current wait events specifically for Client/IPC types.
2. Check overall connection count and utilization against max_connections.
3. Check connection distribution across application_name/pooler identities to spot an undersized or misconfigured pool.
4. Cross-reference with idle-in-transaction findings, since a slow external call mid-transaction produces both symptoms simultaneously.

## 6. Prerequisites

- pg_monitor role membership.
- Visibility into the application/pooler-side connection pool configuration and metrics.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_client_and_ipc_wait_breakdown.sql`](scripts/01_client_and_ipc_wait_breakdown.sql) -- Breaks down current wait events specifically for Client and IPC types to isolate connection-level (as opposed to lock/IO) contention.
2. [`scripts/02_connection_headroom.sql`](scripts/02_connection_headroom.sql) -- Checks whether the database's own max_connections is the limiting factor, or whether it has headroom (pointing at an application/pooler-side limit instead).
3. [`scripts/03_connections_by_pool_identity.sql`](scripts/03_connections_by_pool_identity.sql) -- Breaks connections down by application_name/usename to identify which pool/service is consuming the most connection slots.

## 8. Interpretation Guide

- A high share of ClientRead wait events is normal for many idle connections but abnormal for sessions that should be actively executing a tight request/response loop -- the distinguishing factor is whether the session is inside an open transaction while waiting (see idle-in-transaction) or genuinely between independent statements.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If a pooler is clearly undersized, temporarily increase its pool size within the database's max_connections headroom.

**Short-term remediation** (hours to days):

- Right-size the connection pool based on observed concurrency, not a guess -- use max_connections_headroom findings alongside application-side pool metrics.
- Move PgBouncer (or equivalent) to transaction pooling mode if currently in session mode and the application does not require session-level state, to dramatically improve connection reuse efficiency.

**Long-term engineering fix** (days to weeks):

- Establish connection budget documentation per service so pool sizing is a deliberate capacity decision, not ad hoc (see connections/max-connections-planning).

## 10. Production Safety

- All investigation scripts are read-only.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Root cause is clearly network/application-side -- hand off to SRE/application teams with the gathered evidence rather than continuing database-side tuning.

## 12. Related Issues

- [connection-pooling](../../connections/connection-pooling/README.md)
- [connection-exhaustion](../../connections/connection-exhaustion/README.md)
