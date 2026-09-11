# Database Unavailable

**Category:** Incident Response | **Workflow:** `incident-response/database-unavailable`

## 1. Problem Description

Services report that the database is down: connections are refused, time out, or fail instantly, and trading, deposits, withdrawals and settlement are failing across the board. This workflow covers the first five minutes of that incident -- establishing whether the database is genuinely unavailable, unavailable only to some callers, or completely healthy behind a broken connectivity or pooling layer, before anybody reaches for a failover or a restart.

## 2. Typical Symptoms

- Application logs full of `connection refused`, `could not connect to server`, or connection-timeout errors against the cluster endpoint.
- `FATAL: sorry, too many clients already` returned to new connections while existing sessions keep working normally.
- Health checks for order entry, wallet services and the matching engine failing simultaneously.
- The writer endpoint is unreachable while the reader endpoint still answers, or the reverse.
- A CloudWatch DatabaseConnections cliff, or an instance-level availability event on the cluster.

## 3. Business Impact

- Order entry, cancellation and matching stop entirely -- customers cannot exit positions during a market move, which is simultaneously a financial, reputational and regulatory event.
- Deposits and withdrawals queue or fail, so customer funds appear stuck, driving immediate support escalation and, past a short window, reporting obligations.
- Settlement, risk and compliance jobs miss their windows, creating reconciliation work that outlives the outage itself.
- A misdiagnosed outage -- failing over a database that was actually healthy -- adds a second, self-inflicted outage window on top of the first.

## 4. Possible Root Causes

- Connection-layer: connection slots exhausted (`max_connections` reached), so the database is perfectly healthy but refuses every new session.
- Connection-layer: the pooler (RDS Proxy / PgBouncer) or its host is down, leaving the database healthy but unreachable from the application's point of view.
- Network/infrastructure: a security group, subnet, route or DNS change sending traffic to the wrong or a stale endpoint, often after a failover.
- Cluster-level: an Aurora failover in progress, where the writer endpoint briefly resolves to an instance that is not yet accepting writes.
- Instance-level: the instance restarted (out-of-memory kill, storage event, maintenance action), dropping every pre-existing connection at once.
- Workload-level: a lock storm or runaway query saturating the instance so completely that new connections cannot be serviced inside the client's timeout.
- Authentication: credential rotation or a role change causing every new connection to fail authentication while already-established sessions survive.

## 5. Investigation Strategy

1. Try to connect at all, from a path that does not traverse the application's pooler. If your psql session connects, the postmaster is alive, and that single fact eliminates most 'database is down' hypotheses immediately.
2. Confirm which instance answered and how long it has been up -- an uptime shorter than the incident window means a restart or failover has already happened.
3. Confirm the cluster role and replica topology: are you on the writer, and are the readers healthy and in sync?
4. Check connection-slot saturation, which is the single most common cause of a total-outage report against an otherwise perfectly healthy Aurora cluster.
5. Check the session outcome counters for a spike in fatal, abandoned or killed sessions, which separates a server-side refusal from a client-side disconnect storm.
6. Check for a lock storm or very old transactions paralysing the instance, which makes a healthy database indistinguishable from a dead one.
7. Only after all of the above, consider mitigation: reclaiming slots, restarting the pooler, or escalating a failover decision.

## 6. Prerequisites

- A direct psql path to the cluster that does NOT go through the application's pooler. During a pooler outage this is the only way to reach the database, so it must be established and tested long before the incident.
- `pg_monitor` role membership for the connecting user.
- AWS Console/CLI access for cluster events, instance status, and the CloudWatch DatabaseConnections and CPUUtilization metrics for the cluster.
- Knowledge of which endpoint each service uses (cluster writer endpoint, reader endpoint, custom endpoint, or a pooler address).

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_instance_identity_and_uptime.sql`](scripts/01_instance_identity_and_uptime.sql) -- Confirms the database is reachable at all, and identifies exactly which instance answered, its role, and how long it has been running.
2. [`scripts/02_cluster_role_and_replica_status.sql`](scripts/02_cluster_role_and_replica_status.sql) -- Establishes cluster topology: whether this connection is on the writer or a reader, and the Aurora-reported status and lag of every instance in the cluster.
3. [`scripts/03_connection_slot_saturation.sql`](scripts/03_connection_slot_saturation.sql) -- Checks whether the cluster is refusing new connections because its connection slots are full -- the most common cause of a total-outage report against a healthy database.
4. [`scripts/04_session_outcome_counters.sql`](scripts/04_session_outcome_counters.sql) -- Distinguishes server-side refusals from client-side disconnects using the per-database session outcome counters.
5. [`scripts/05_blocked_and_stuck_sessions.sql`](scripts/05_blocked_and_stuck_sessions.sql) -- Checks whether the instance is alive but effectively paralysed by blocking or by very old open transactions.
6. [`scripts/06_availability_mitigation_actions.md`](scripts/06_availability_mitigation_actions.md) -- Guarded runbook for the small set of actions that can restore access during an availability incident: reclaiming connection slots, ending a paralysing session, and deciding whether a failover is justified.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Aurora's writer endpoint is a DNS record that moves during a failover. A client with a cached DNS entry (a JVM with an infinite DNS TTL is the classic case) keeps connecting to the old writer, which is now a reader, and every write fails with a read-only transaction error while the cluster is perfectly healthy -- always confirm `pg_is_in_recovery()` on the connection that is actually failing.
- `max_connections` on Aurora is derived from the instance class's memory through the parameter-group formula rather than freely chosen, so 'just raise max_connections' is not a valid immediate mitigation: it needs a parameter-group change and, in most cases, a restart.
- Aurora cluster events (failover, restart, storage, maintenance) are visible in the RDS console and via `aws rds describe-events`, not in any SQL catalog. Pull them in parallel with these scripts, because they frequently contain the actual answer.

## 8. Interpretation Guide

- If script 01 returns a row, the database is UP. Say so explicitly in the incident channel: it redirects the entire response from 'restore the database' to 'restore access to the database', which are completely different actions with completely different risk profiles.
- `instance_uptime` shorter than the incident duration means the instance restarted or failed over. Stop looking for a live workload cause and pivot to the failover investigation.
- `is_reader_instance = true` when you expected the writer means the writer endpoint resolved to a reader (failover in progress, or a stale DNS cache in the client). Writes fail with a read-only transaction error while the cluster itself is entirely healthy.
- `pct_utilized` at or near 100% in script 03 means the database is refusing new connections while serving existing ones perfectly -- that is connection exhaustion, not an outage.
- A large `sessions_abandoned` jump with normal `sessions_fatal` points at the client side: an application crash-loop, pod evictions, or a load balancer cutting idle connections.
- A large `sessions_fatal` jump points at the server side: out of slots, authentication failures, or backends being terminated.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If connection slots are exhausted, reclaim slots by ending long-idle sessions per the guarded runbook in this workflow, and in the same minute tell the owning service to reduce its pool size -- reclaiming slots without fixing the source just refills them within seconds.
- If the pooler is the failure point, either fail application traffic over to the direct cluster endpoint (only if the connection count allows it) or restart the pooler, per the runbook.
- If a failover is in progress, do nothing to the database. Let the endpoint converge and confirm that applications are retrying with backoff rather than hot-looping, which is what turns a 30-second failover into a connection storm.
- If a lock storm or runaway query is saturating the instance, switch to the lock-storm or runaway-query workflow in this category -- the unavailability is a symptom, not the cause.

**Short-term remediation** (hours to days):

- Right-size connection pools against the instance's actual `max_connections`, with a documented per-service budget whose total leaves real headroom.
- Put a pooler (RDS Proxy, or PgBouncer in transaction mode) in front of every service with high connection churn, so a service restart cannot storm the database with fresh connections.
- Set `idle_in_transaction_session_timeout` and a sane `statement_timeout` per application role so no single misbehaving client can hold slots indefinitely.
- Add connection retry with exponential backoff and jitter to every service, so a brief failover does not become a self-inflicted connection storm.

**Long-term engineering fix** (days to weeks):

- Reserve connection headroom explicitly for operators: a break-glass role and connection path that application traffic never uses, so responders can always get in.
- Run regular failover game days, so application behaviour during an endpoint change is a known quantity instead of a discovery made mid-incident.
- Build a cluster availability dashboard combining DatabaseConnections, CPUUtilization, writer/reader role and pooler health, so 'is the database down' is answered by a graph in seconds rather than by an investigation.

## 10. Production Safety

- Scripts 01-05 are strictly read-only and safe to run during a total outage -- they read catalogs and statistics views only, and take no locks beyond brief catalog lookups.
- Script 06 is a guarded manual runbook that can end other sessions; read it fully before executing any statement in it.
- Never restart or fail over a cluster as a first response. If the database is answering queries, a failover converts a partial incident into a guaranteed full write-outage window.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- You cannot connect at all from a known-good direct path -- escalate immediately to AWS support and database engineering leadership, and start the disaster-recovery assessment in parallel.
- The instance restarted with no explanation in the cluster events -- escalate to database engineering, because an unexplained restart tends to recur.
- Deposits or withdrawals have been failing for more than a few minutes -- escalate to the treasury and compliance on-call in parallel with the technical fix, because customer-funds visibility carries its own reporting obligations.
- Restoring access requires a failover or an instance-class change beyond on-call authority.

## 12. Related Issues

- [production-triage](../production-triage/README.md)
- [connection-exhaustion](../connection-exhaustion/README.md)
- [lock-storm](../lock-storm/README.md)
- [connection-exhaustion](../../connections/connection-exhaustion/README.md)
- [failover-investigation](../../replication-and-ha/failover-investigation/README.md)
- [disaster-recovery](../../disaster-recovery/README.md)
