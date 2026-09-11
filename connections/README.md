# Connection Management

**Category:** `connections`

This is the index for the `connections/` category: every workflow
(issue directory) below addresses a distinct, real operational problem or
DBA use case for this Aurora PostgreSQL toolkit, per the repository's
one-parent-directory-per-problem design. Each workflow directory is
self-contained -- its own `README.md` (problem description, symptoms,
business impact, root causes, investigation strategy, prerequisites,
interpretation guide, remediation options, production safety, and
escalation criteria) and a `scripts/` directory of numbered, read-only-by
-default investigation scripts (see each workflow's `scripts/README.md`
for the full script-by-script execution table).

## Workflows

| Workflow | Summary |
| --- | --- |
| [`connection-exhaustion`](connection-exhaustion/README.md) | The database is at or near max_connections, causing new connection attempts to be rejected outright -- a full application-facing outage for any service unable to obtain a connection. |
| [`connection-spikes`](connection-spikes/README.md) | A sudden, sharp increase in connection count over a short period, whether or not it reaches full exhaustion -- often a leading indicator of exhaustion or of a reconnect storm. |
| [`idle-connections`](idle-connections/README.md) | A large number of connections sitting fully idle (not idle-in-transaction, just idle) -- consuming a connection slot and a small amount of backend memory without doing any work, potentially crowding out headroom for active work. |
| [`idle-in-transaction`](idle-in-transaction/README.md) | Connection-management-focused entry point for idle-in-transaction sessions; see concurrency-and-locking/idle-in-transaction for the full lock/concurrency-impact investigation of the same underlying sessions. |
| [`connection-pooling`](connection-pooling/README.md) | Guidance and database-side diagnostics for environments using PgBouncer (or an equivalent external pooler) in front of Aurora PostgreSQL, clearly separating what is visible/actionable from the PostgreSQL side vs. what must be investigated on the pooler itself. |
| [`max-connections-planning`](max-connections-planning/README.md) | Proactive capacity planning workflow for establishing an appropriate max_connections budget and per-service connection allocation, rather than reacting to exhaustion after the fact. |
| [`application-connection-analysis`](application-connection-analysis/README.md) | Deep-dive into a specific application/service's connection behavior -- pool size, connection lifetime, and query pattern -- when that service is suspected of contributing disproportionately to connection-related issues. |

## Related Categories

- [`concurrency-and-locking/connection-contention`](../../concurrency-and-locking/connection-contention/README.md)
- [`concurrency-and-locking/idle-in-transaction`](../../concurrency-and-locking/idle-in-transaction/README.md)
- [`performance/performance-after-failover`](../../performance/performance-after-failover/README.md)

Start with the workflow whose title most closely matches the symptom you are
investigating; if uncertain, `database-health/comprehensive-health-check`
and `incident-response/production-triage` both provide a broad first pass
that surfaces which specific workflow to open next.
