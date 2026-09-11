# Application Timeouts

**Category:** Incident Response | **Workflow:** `incident-response/application-timeouts`

## 1. Problem Description

Services are reporting database timeouts -- statement timeouts, pool-acquisition timeouts, or client-side deadline expiry -- and the question is whether the database is actually slow, or whether a timeout is set too aggressively, or whether the bottleneck is in the pooler or the network. This workflow answers that question quickly, because the three causes have completely different fixes and only one of them is a database problem.

## 2. Typical Symptoms

- Application errors citing `canceling statement due to statement timeout` (SQLSTATE 57014) or a framework-level query timeout.
- Connection-pool acquisition timeouts with no corresponding database-side error at all.
- Timeouts concentrated in one service or one endpoint while everything else behaves normally.
- Timeouts that started immediately after a configuration change, a deployment, or a credential/role change.
- Retry storms visible as a high call count on a small set of statements.

## 3. Business Impact

- Timeouts on the order path surface to customers as failed placements or cancellations, and during volatility a failed cancel is a direct financial loss for the customer.
- Timeouts that the application handles by retrying multiply database load, so an aggressive timeout can be the cause of the slowness it is reacting to.
- Withdrawal and deposit flows that fail open on timeout risk double-processing; flows that fail closed strand customer funds. Both outcomes attract compliance attention.

## 4. Possible Root Causes

- The database genuinely is slow: blocking, resource saturation, or a plan regression, and the timeout is doing its job.
- The timeout is set too aggressively for the query's honest runtime, so normal work is being killed.
- A role- or database-level timeout override that nobody remembers applying, making one role behave differently from another running the same query.
- Pool-acquisition timeouts rather than statement timeouts: the request never reached the database at all, so nothing is visible in database-side statistics.
- Network or pooler latency between the application and the database inflating the end-to-end deadline while server-side execution time stays fine.
- A lock wait, which looks identical to slowness from the application's side but needs a completely different fix.
- Connection exhaustion, which presents as a timeout in almost every client library.

## 5. Investigation Strategy

1. Read the effective timeout settings on the server first -- statement_timeout, lock_timeout and idle_in_transaction_session_timeout.
2. Check the role- and database-level overrides, because that is where surprising per-service differences almost always live.
3. Check the session outcome counters for evidence of who is ending sessions and how.
4. Check whether sessions are blocked, since a lock wait is the most common cause of a timeout that has nothing to do with query cost.
5. Check connection headroom, because pool-acquisition timeouts caused by exhaustion never appear as database-side slowness at all.
6. Decide which of the three worlds you are in -- database slow, timeout too tight, or never-reached-the-database -- and act accordingly.

## 6. Prerequisites

- `pg_monitor` role membership.
- The application's own timeout configuration: pool acquisition timeout, socket timeout, and any framework-level query deadline. Server-side settings alone cannot explain a client-side timeout.
- The exact error text and SQLSTATE from the application logs -- 57014 (statement timeout), 57P01 (terminated), and a pool-acquisition timeout are three entirely different incidents.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_effective_timeout_settings.sql`](scripts/01_effective_timeout_settings.sql) -- Reads the timeout and concurrency settings this connection actually resolved to.
2. [`scripts/02_role_and_database_overrides.sql`](scripts/02_role_and_database_overrides.sql) -- Shows the per-role and per-database setting overrides that explain why one service times out while another does not.
3. [`scripts/03_session_outcome_counters.sql`](scripts/03_session_outcome_counters.sql) -- Checks how sessions are actually ending, which separates server-side cancellation from client-side abandonment.
4. [`scripts/04_blocking_and_waits.sql`](scripts/04_blocking_and_waits.sql) -- Checks whether the timeouts are lock waits in disguise -- the most common cause of a timeout that has nothing to do with query cost.
5. [`scripts/05_connection_headroom.sql`](scripts/05_connection_headroom.sql) -- Checks whether the timeouts are actually pool-acquisition failures caused by connection exhaustion.
6. [`scripts/06_timeout_mitigation_actions.md`](scripts/06_timeout_mitigation_actions.md) -- Guarded runbook for the timeout-specific actions: adjusting role-level timeouts safely, adding lock_timeout, and capping retries.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- On Aurora, cluster-wide defaults for statement_timeout and lock_timeout come from the DB cluster parameter group rather than postgresql.conf, and ALTER SYSTEM is not available for them -- role-level ALTER ROLE ... SET remains the correct in-database mechanism for a per-service override.
- RDS Proxy imposes its own connection borrow timeout; when a proxy is in the path, a client-reported timeout may have expired while waiting for the proxy to lend a database connection, and nothing about it will ever appear in this database's statistics.
- Aurora failovers cause a short burst of connection errors and timeouts by design; before treating a brief timeout spike as a workload problem, check the cluster events for a failover in the same minute.

## 8. Interpretation Guide

- If the error is SQLSTATE 57014, the database killed the statement on purpose and the server-side timeout setting is the relevant configuration -- find which layer set it using script 02.
- If the application reports a timeout but the database shows no statement timeout and no long-running queries, the request likely never reached the database: suspect the pool, the proxy or the network.
- A statement_timeout of 0 for the affected role means the server is not the one timing out, so the deadline is client-side however the error is worded.
- Blocked sessions in script 04 mean the timeouts are lock waits in disguise; tuning queries will not help and the lock-storm workflow will.
- Connection utilization near the ceiling in script 05 explains pool-acquisition timeouts completely, and that is a connection incident rather than a query one.
- Timeouts that affect exactly one role while another role runs the same query successfully is almost always a pg_db_role_setting override -- script 02 finds it in seconds.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If the database is genuinely slow, stop reading this workflow and go fix the slowness through the lock-storm, runaway-query or latency workflow -- the timeout is a messenger.
- If the timeout is too tight for honest work, agree a temporary role-level increase with the owning team and record it as an incident-scoped change with a revert step.
- If it is a pool-acquisition timeout, treat it as connection exhaustion and use that workflow.
- Confirm the application's retry behaviour: unbounded retries on timeout turn a small slowdown into a self-sustaining incident, and capping them is often the single most effective immediate action.

**Short-term remediation** (hours to days):

- Set explicit, intentional per-role timeouts rather than inheriting a cluster default: a trading API role and a reconciliation role should not share one statement_timeout.
- Set `lock_timeout` alongside `statement_timeout` so lock waits fail fast and distinguishably, instead of consuming the entire statement budget and reporting as generic slowness.
- Align client-side deadlines with server-side timeouts so the two layers cannot disagree about who owns the failure.

**Long-term engineering fix** (days to weeks):

- Document a timeout budget per service tier -- trading path, funds movement, reporting -- and enforce it in role configuration rather than in scattered application settings.
- Instrument the application to distinguish pool-acquisition time from query execution time, so this triage takes seconds next time instead of minutes.
- Require exponential backoff with jitter and a retry cap on every database call, so retries dampen an incident instead of amplifying it.

## 10. Production Safety

- Scripts 01-05 are read-only and safe to run at any time.
- Script 06 changes role-level configuration affecting live traffic; read it fully and get the owning team's agreement before applying anything.
- Never raise or remove a timeout globally to make errors stop. Timeouts are the mechanism that prevents one slow statement from consuming every connection, and removing them converts a visible incident into a silent, much larger one.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Timeouts affect funds-movement flows (deposits, withdrawals, settlement) -- escalate to treasury and compliance immediately, because the failure mode determines whether funds are stranded or at risk of double-processing.
- The application cannot distinguish pool-acquisition timeouts from statement timeouts, so the investigation cannot be completed from the database side -- escalate to the owning service to add that instrumentation.
- Server-side execution times are healthy but end-to-end latency is not, which points at the network or pooler -- escalate to the platform team.
- A timeout change is requested on a role used by settlement or reconciliation -- that requires named approval, not an on-call judgement call.

## 12. Related Issues

- [production-triage](../production-triage/README.md)
- [sudden-latency-spike](../sudden-latency-spike/README.md)
- [lock-storm](../lock-storm/README.md)
- [connection-exhaustion](../connection-exhaustion/README.md)
- [connection-exhaustion](../../connections/connection-exhaustion/README.md)
- [blocked-queries](../../concurrency-and-locking/blocked-queries/README.md)
