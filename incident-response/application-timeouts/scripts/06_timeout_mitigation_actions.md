# 06_timeout_mitigation_actions

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `06_timeout_mitigation_actions.md` |
| Purpose | Guarded runbook for the timeout-specific actions: adjusting role-level timeouts safely, adding lock_timeout, and capping retries. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance (role-level settings are cluster-wide configuration stored in the catalog). |
| Safety | ELEVATED RISK -- MANUAL EXECUTION ONLY, CHANGES CONFIGURATION THAT AFFECTS LIVE PRODUCTION TRAFFIC (read every warning in this file first) |
| Expected impact | Role-level timeout changes alter how the affected service's statements fail, for new sessions only. No data is modified by any statement in this file. |
| Required privileges | Membership in the target role, or a role with CREATEROLE/ownership over it, is required to run ALTER ROLE ... SET. On Aurora this is typically `rds_superuser`. |
| Prerequisites | Scripts 01-05 completed, blocking and connection exhaustion ruled out, and the owning team's agreement for any change plus a named owner for the revert step. |
| Execution order | Step 06 of workflow `incident-response/application-timeouts` |
| Related scripts | 02_role_and_database_overrides.sql, 04_blocking_and_waits.sql, 05_connection_headroom.sql |

## How to interpret / use this runbook

Use the three-worlds table first -- it is the whole point of this file. Only continue past it when blocking and connection exhaustion have both been ruled out, because a timeout change is the wrong fix for either of those.

---

## First, decide which of the three worlds you are in

| Evidence | World | Correct action |
|---|---|---|
| Script 04 shows blocked sessions | The database is blocked | Clear the blocker: `../lock-storm/README.md`. Do not touch timeouts. |
| Script 05 shows utilization near the ceiling | Requests never reach the database | Treat as connection exhaustion: `../connection-exhaustion/README.md`. |
| Neither, and server-side execution times look healthy | The timeout is misconfigured, or the latency is outside the database | Continue below. |

Changing a timeout while the real cause is blocking or exhaustion hides the
incident without fixing it, which is strictly worse than leaving it visible.

## Action A -- adjust a role-level statement timeout

*Precondition: script 02 shows the role's current value, and the owning team
agrees the honest runtime of their query genuinely exceeds it.*

```sql
-- Applies to NEW sessions of this role only. Existing pooled sessions keep the
-- old value until they are recycled, so expect a gradual rather than an instant
-- change in behaviour.
ALTER ROLE <role_name> SET statement_timeout = '15s';

-- Revert step, to be executed once the underlying query is fixed:
ALTER ROLE <role_name> RESET statement_timeout;
```

Raise it to the smallest value that lets honest work complete, and record the
revert step and its owner in the incident channel at the same time. An
incident-scoped timeout increase that nobody reverts becomes next quarter's
connection-exhaustion incident.

Never set `statement_timeout = 0` on an application role to make errors stop.
That removes the only mechanism preventing one pathological statement from
occupying a connection indefinitely.

## Action B -- add a lock timeout so lock waits fail fast and distinguishably

*Precondition: script 04 showed lock waits contributing to the timeouts.*

Without `lock_timeout`, a statement blocked on a lock burns its entire
`statement_timeout` budget and then reports as a generic slow query -- which is
exactly why this class of incident is so often misdiagnosed:

```sql
ALTER ROLE <role_name> SET lock_timeout = '2s';
ALTER ROLE <role_name> RESET lock_timeout;   -- revert step
```

Set `lock_timeout` well below `statement_timeout` so the two failure modes are
distinguishable in the application's error logs.

## Action C -- cap retries (application side, highest leverage)

This is not a database change, and it is frequently the single most effective
action available. Unbounded retries on timeout multiply load on a database that
is already struggling, which is how a 200ms hiccup becomes a 20-minute incident.

Ask the owning service for: exponential backoff with jitter, a hard retry cap,
and a circuit breaker that stops retrying entirely once the error rate crosses a
threshold.

## Action D -- protect funds-movement flows

Timeouts on deposit, withdrawal and settlement paths need an explicit decision
about failure semantics, not just a number:

* Failing **open** (proceeding on timeout) risks double-processing a movement.
* Failing **closed** (rejecting on timeout) strands customer funds temporarily.

Neither is a database setting, and neither is an on-call decision. Escalate to
treasury and compliance and record the chosen semantics in the incident log.

## Verify

Re-run `03_session_outcome_counters.sql` a few minutes after any change and
compare the deltas. Falling sessions_abandoned and sessions_fatal means the
change is working; unchanged counters mean you changed the wrong layer.
