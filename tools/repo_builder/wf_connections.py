"""Workflow definitions: connections/ category (7 issue directories)."""
from __future__ import annotations

from typing import List

from . import sql_blocks as sb
from .helpers import PG_MONITOR, md_script, sql_script
from .model import Workflow

CATEGORY_SLUG = "connections"
CATEGORY_TITLE = "Connection Management"


def _wf(**kwargs) -> Workflow:
    kwargs.setdefault("category_slug", CATEGORY_SLUG)
    kwargs.setdefault("category_title", CATEGORY_TITLE)
    return Workflow(**kwargs)


WORKFLOWS: List[Workflow] = []

WORKFLOWS.append(_wf(
    slug="connection-exhaustion",
    title="Connection Exhaustion",
    summary="The database is at or near max_connections, causing new connection attempts to be rejected outright -- a full application-facing outage for any service unable to obtain a connection.",
    symptoms=["Application errors: 'FATAL: too many connections for role/database' or 'sorry, too many clients already'.", "Connection count in pg_stat_activity at or very near max_connections."],
    business_impact=["Connection exhaustion is a hard outage for any new request needing a database connection -- existing connections continue to work, but no new work can start, which for a trading platform means new orders/logins fail outright."],
    root_causes=["A connection leak in an application/service (connections opened but never returned to the pool).", "A pool misconfiguration deploying far more application instances/pool-size than the database's max_connections budget.", "A sudden burst of legitimate demand (traffic spike, market volatility) exceeding provisioned capacity.", "No connection pooler in front of the database at all, with each application instance connecting directly."],
    investigation_strategy=["Confirm current utilization against max_connections.", "Break down connections by application_name/usename to find the specific source.", "Check for a large number of idle connections (potential leak/pool misconfiguration) vs. active connections (genuine demand)."],
    prerequisites=["pg_monitor role membership."],
    interpretation_guide=["A large idle_count relative to active_count for a specific application_name points to a leak or an oversized/misconfigured pool holding connections unnecessarily -- distinct from genuine demand, which shows up as a high active_count."],
    remediation_immediate=["If a specific application/service is clearly leaking connections, restart it to release them as an immediate mitigation while the underlying bug is fixed.", "If genuinely legitimate demand has exceeded capacity, and Aurora max_connections headroom exists at a larger instance class, consider an emergency vertical scale."],
    remediation_short_term=["Introduce or right-size a connection pooler (PgBouncer) in front of the database to multiplex many application connections onto fewer database connections.", "Fix the specific application-side leak (missing connection.close()/context-manager usage)."],
    remediation_long_term=["Establish a documented per-service connection budget (see max-connections-planning) so total planned connections never approach max_connections under normal peak conditions."],
    production_safety=["All investigation scripts are read-only."],
    escalation_criteria=["The root cause is an application bug causing a leak -- escalate to the owning team immediately, since restarting the service is only a temporary mitigation."],
    related_issues=["../connection-pooling/README.md", "../max-connections-planning/README.md", "../../concurrency-and-locking/connection-contention/README.md"],
    aurora_notes=["On Aurora, max_connections is typically derived automatically from the instance class's memory via a parameter-group formula rather than freely configurable -- increasing it substantially usually means moving to a larger instance class, not just editing a parameter."],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_connection_headroom", "Checks current connection utilization against max_connections.",
               sb.max_connections_headroom(),
               "pct_utilized near 100% confirms exhaustion is imminent/active; note superuser_reserved_connections, which further reduces the pool available to ordinary application roles.",
               related_scripts="02_connections_by_application.sql"),
    sql_script("02", "02_connections_by_application", "Breaks connections down by application_name/usename/state to identify the source.",
               sb.connections_by_application_and_user(),
               "A single application_name with a disproportionate idle_count suggests a leak or oversized pool; a broad, even increase across all applications suggests genuine demand growth.",
               related_scripts="../connection-pooling/README.md"),
]

WORKFLOWS.append(_wf(
    slug="connection-spikes",
    title="Connection Spikes",
    summary="A sudden, sharp increase in connection count over a short period, whether or not it reaches full exhaustion -- often a leading indicator of exhaustion or of a reconnect storm.",
    symptoms=["Connection count chart showing a sharp step-change rather than gradual growth.", "Correlates with a deployment, a failover, or an upstream outage causing widespread client reconnects."],
    business_impact=["Connection spikes stress both the database (context switching, memory) and any pooler in front of it, and frequently precede a connection-exhaustion incident if not addressed."],
    root_causes=["A deployment restarting many application instances simultaneously, each re-establishing its full connection pool at once.", "A failover triggering a synchronized reconnect storm across all connected clients.", "An upstream dependency outage causing widespread client-side retries that each open a new connection instead of reusing an existing one."],
    investigation_strategy=["Confirm the spike's timing against known events (deploys, failovers).", "Break down the spike by application_name to identify the source.", "Check whether reconnecting clients are using appropriate backoff/jitter."],
    prerequisites=["pg_monitor role membership; deployment/event timeline for correlation."],
    interpretation_guide=["A spike that resolves on its own within seconds to a couple of minutes and correlates with a known event (deploy/failover) is expected and low-risk; a spike that persists or continues climbing needs active investigation as a potential leak or retry storm."],
    remediation_immediate=["If the spike is actively risking exhaustion, apply connection-exhaustion's immediate remediation."],
    remediation_short_term=["Stagger application instance restarts/deploys (rolling restarts) instead of all-at-once to smooth reconnection load."],
    remediation_long_term=["Ensure all client-side reconnect logic uses randomized backoff/jitter to avoid synchronized reconnect storms."],
    production_safety=["Read-only."],
    escalation_criteria=["Spike does not correlate with any known event and continues growing -- escalate as a potential leak/incident."],
    related_issues=["../connection-exhaustion/README.md", "../../performance/performance-after-failover/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_connection_state_snapshot", "Snapshots current connection counts by state as the starting point for spike investigation.",
               sb.connections_by_state(),
               "Re-run this every few seconds during an active spike to track its trajectory; compare against the pre-spike baseline.",
               related_scripts="02_connections_by_application.sql"),
    sql_script("02", "02_connections_by_application", "Attributes the spike to a specific application/service.",
               sb.connections_by_application_and_user(),
               "The application_name showing the largest delta from its normal baseline is the source of the spike.",
               related_scripts="../connection-exhaustion/README.md"),
]

WORKFLOWS.append(_wf(
    slug="idle-connections",
    title="Idle Connections",
    summary="A large number of connections sitting fully idle (not idle-in-transaction, just idle) -- consuming a connection slot and a small amount of backend memory without doing any work, potentially crowding out headroom for active work.",
    symptoms=["High idle_count relative to active_count in connection breakdowns.", "Connection count near max_connections despite low actual query throughput."],
    business_impact=["Idle connections are lower-risk than idle-in-transaction (they hold no locks/snapshots) but still consume a connection slot -- at scale, they can still contribute to exhaustion and represent inefficient pool sizing."],
    root_causes=["A connection pool sized much larger than actual concurrent demand requires.", "A pooler in session mode holding connections open between client requests instead of returning them to a shared pool.", "Application instances that open a connection per long-lived worker/thread regardless of actual utilization."],
    investigation_strategy=["Break down idle connections by application_name.", "Compare pool size configuration against observed active concurrency to right-size it."],
    prerequisites=["pg_monitor role membership; visibility into application/pooler pool-size configuration."],
    interpretation_guide=["A small, stable number of idle connections per application is normal and healthy (pool warm-up); a very large number relative to peak active concurrency suggests over-provisioned pool sizing."],
    remediation_immediate=["None typically required unless contributing to active exhaustion."],
    remediation_short_term=["Right-size pool `min`/`max` settings based on observed peak active concurrency, not a guess.", "Switch a session-mode pooler to transaction-mode pooling if the application does not require session-level state."],
    remediation_long_term=["Document connection budgets per service (see max-connections-planning)."],
    production_safety=["Read-only."],
    escalation_criteria=["N/A -- typically a low-urgency tuning finding."],
    related_issues=["../connection-pooling/README.md", "../max-connections-planning/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_idle_connections_by_application", "Breaks down idle (not idle-in-transaction) connections by application to assess pool sizing.",
               sb.connections_by_application_and_user(),
               "A consistently high idle_count for a specific application_name, far above its active_count, is a right-sizing opportunity for that service's pool.",
               related_scripts="../connection-pooling/README.md"),
]

WORKFLOWS.append(_wf(
    slug="idle-in-transaction",
    title="Idle-in-Transaction (Connections View)",
    summary="Connection-management-focused entry point for idle-in-transaction sessions; see concurrency-and-locking/idle-in-transaction for the full lock/concurrency-impact investigation of the same underlying sessions.",
    symptoms=["See concurrency-and-locking/idle-in-transaction."],
    business_impact=["Beyond the lock/vacuum impact covered in concurrency-and-locking, idle-in-transaction sessions also consume a connection slot exactly as if they were doing useful work."],
    root_causes=["See concurrency-and-locking/idle-in-transaction."],
    investigation_strategy=["List idle-in-transaction sessions and their connection-slot impact.", "Cross-reference with concurrency-and-locking/idle-in-transaction for lock impact."],
    prerequisites=["pg_monitor role membership."],
    interpretation_guide=["Treat any idle-in-transaction session as both a connection-budget concern and a lock/vacuum concern simultaneously."],
    remediation_immediate=["See concurrency-and-locking/idle-in-transaction."],
    remediation_short_term=["Set idle_in_transaction_session_timeout at the role/database level."],
    remediation_long_term=["See concurrency-and-locking/idle-in-transaction."],
    production_safety=["Read-only."],
    escalation_criteria=["See concurrency-and-locking/idle-in-transaction."],
    related_issues=["../../concurrency-and-locking/idle-in-transaction/README.md", "../connection-exhaustion/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_idle_in_transaction_sessions", "Lists idle-in-transaction sessions, viewed here for their connection-slot consumption impact.",
               sb.idle_in_transaction_sessions(),
               "Every result here occupies a connection slot indefinitely in addition to holding locks/snapshots -- see concurrency-and-locking/idle-in-transaction for the full remediation guidance.",
               related_scripts="../../concurrency-and-locking/idle-in-transaction/scripts/01_idle_in_transaction_sessions.sql"),
]

WORKFLOWS.append(_wf(
    slug="connection-pooling",
    title="Connection Pooling (PgBouncer) Considerations",
    summary="Guidance and database-side diagnostics for environments using PgBouncer (or an equivalent external pooler) in front of Aurora PostgreSQL, clearly separating what is visible/actionable from the PostgreSQL side vs. what must be investigated on the pooler itself.",
    symptoms=["Application-visible connection errors that do not correlate with the database's own max_connections utilization -- often a sign the bottleneck is the pooler layer, not PostgreSQL."],
    business_impact=["A correctly configured pooler is essential infrastructure for a high-connection-concurrency exchange workload; pooler misconfiguration is a very common source of connection-related incidents that are misdiagnosed as database problems."],
    root_causes=["Pooler pool_size too small for actual concurrency needs.", "Pooler in session mode instead of transaction mode, multiplying effective connection consumption.", "Pooler itself under CPU/memory pressure (a separate host/process from the database entirely)."],
    investigation_strategy=["From the database side: confirm how many connections the pooler itself is actually using against max_connections (should be a small, stable number in transaction-pooling mode).", "From the pooler side (not a PostgreSQL SQL concern): check PgBouncer's own SHOW POOLS / SHOW STATS admin console for pooler-side queue depth and wait times."],
    prerequisites=["Administrative access to the PgBouncer instance's admin console for pooler-side diagnostics (outside the scope of PostgreSQL SQL entirely)."],
    interpretation_guide=["If the database shows ample max_connections headroom while the application experiences connection errors/timeouts, the problem is almost certainly on the pooler side (or between the application and the pooler), not in PostgreSQL -- do not keep searching PostgreSQL-side catalogs for a pooler-side problem."],
    remediation_immediate=["Increase PgBouncer pool_size (pooler-side config, not a PostgreSQL change) if pooler-side queuing is confirmed."],
    remediation_short_term=["Move from session to transaction pooling mode if application compatibility allows (no session-level SET/temp tables/prepared statements relied upon across statements)."],
    remediation_long_term=["Document the intended pooler architecture (per-service PgBouncer vs. shared, pool_size per service) as part of max-connections-planning."],
    production_safety=["Database-side diagnostics here are read-only; pooler-side changes are outside PostgreSQL's safety model entirely and follow the pooler's own operational practices."],
    escalation_criteria=["Pooler-side issues are outside DBA/PostgreSQL scope in many organizations -- escalate to the team owning the pooler infrastructure if the database side is confirmed healthy."],
    related_issues=["../connection-exhaustion/README.md", "../max-connections-planning/README.md"],
    aurora_notes=["Aurora does not provide a managed PgBouncer -- pooling is an application/infrastructure-team responsibility layered in front of the Aurora endpoint(s), typically run on separate EC2/ECS/Fargate infrastructure or as a sidecar."],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_pooler_connection_footprint", "Checks how many database-side connections the pooler's application_name/user is actually consuming, to distinguish a database-side vs. pooler-side bottleneck.",
               sb.connections_by_application_and_user(),
               "A small, stable connection count here despite application-visible connection errors strongly suggests the bottleneck is on the pooler side (or between application and pooler) -- pivot to the pooler's own admin console (SHOW POOLS) rather than continuing PostgreSQL-side investigation.",
               related_scripts="../connection-exhaustion/README.md"),
]

WORKFLOWS.append(_wf(
    slug="max-connections-planning",
    title="max_connections Capacity Planning",
    summary="Proactive capacity planning workflow for establishing an appropriate max_connections budget and per-service connection allocation, rather than reacting to exhaustion after the fact.",
    symptoms=["No active symptom -- proactive planning workflow, typically run during capacity reviews or before onboarding a new service."],
    business_impact=["A documented, deliberately planned connection budget prevents the class of incident covered by connection-exhaustion from recurring as the platform adds more services."],
    root_causes=["N/A -- planning workflow."],
    investigation_strategy=["Establish current total connection budget (max_connections minus reserved).", "Inventory current per-service allocation.", "Compare against each service's actual peak observed usage to find both over- and under-provisioned services."],
    prerequisites=["pg_monitor role membership; inventory of all services connecting to the database."],
    interpretation_guide=["The sum of all services' pool `max` settings should never exceed a safe fraction (commonly 70-80%) of max_connections, leaving explicit headroom for migrations, monitoring tools, and burst capacity."],
    remediation_immediate=["N/A."],
    remediation_short_term=["Right-size any service found significantly over- or under-provisioned relative to its actual observed peak usage."],
    remediation_long_term=["Maintain a living connection-budget document reviewed whenever a new service is onboarded or Aurora instance class changes (which changes the effective max_connections ceiling)."],
    production_safety=["Read-only."],
    escalation_criteria=["Planned service growth would exceed available connection budget even after pooling -- escalate for an instance-class or architecture decision (e.g. mandatory pooling for all new services) ahead of actually hitting exhaustion."],
    related_issues=["../connection-exhaustion/README.md", "../connection-pooling/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_current_budget_and_allocation", "Establishes current max_connections budget and per-application actual usage as the planning baseline.",
               sb.connections_by_application_and_user(),
               "Sum peak session_count per application_name across your monitoring window and compare against max_connections headroom (see 02_connection_headroom.sql in connection-exhaustion) to build the capacity plan.",
               related_scripts="../connection-exhaustion/scripts/01_connection_headroom.sql"),
]

WORKFLOWS.append(_wf(
    slug="application-connection-analysis",
    title="Application-Level Connection Analysis",
    summary="Deep-dive into a specific application/service's connection behavior -- pool size, connection lifetime, and query pattern -- when that service is suspected of contributing disproportionately to connection-related issues.",
    symptoms=["A specific service is repeatedly implicated in connection-exhaustion/connection-spikes findings."],
    business_impact=["Understanding one service's specific connection behavior in detail is necessary to fix a recurring, service-specific connection problem rather than repeatedly applying database-wide mitigations."],
    root_causes=["See connection-exhaustion and idle-connections for the general root-cause list; this workflow narrows the investigation to one specific, already-implicated service."],
    investigation_strategy=["Filter all connection/activity views to the specific application_name.", "Characterize its connection count, state distribution, and typical query pattern over time.", "Compare against its documented/expected pool configuration."],
    prerequisites=["The specific application_name/usename already identified as the focus, typically from connection-exhaustion or connection-spikes."],
    interpretation_guide=["Compare the service's actual observed behavior against its own configuration (pool min/max, statement timeout) -- a mismatch (e.g. actual connections far exceeding configured pool max) suggests either multiple unpooled instances or a configuration drift, not a single simple leak."],
    remediation_immediate=["Coordinate directly with the owning team using the specific evidence gathered here."],
    remediation_short_term=["Fix the specific configuration/code issue identified."],
    remediation_long_term=["Add this service's connection budget to max-connections-planning's living documentation."],
    production_safety=["Read-only."],
    escalation_criteria=["The owning team cannot resolve the issue without a broader architecture change (e.g. adopting pooling for the first time) -- escalate to database engineering and that team's leadership jointly."],
    related_issues=["../connection-exhaustion/README.md", "../max-connections-planning/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_service_connection_detail", "Detailed connection/state/query breakdown filtered to a specific application, for deep-dive analysis.",
               """
-- Detailed per-session view for a specific application, to characterize its
-- exact connection and query behavior for a targeted investigation. This
-- is a WHERE-clause filter (not a relation reference), so an unmatched
-- default application name simply returns zero rows -- edit the \\set line
-- below to the real application_name under investigation.
\\set target_application_name 'order-service'
SELECT
    pid,
    usename,
    client_addr,
    state,
    backend_start,
    now() - backend_start                                        AS connection_age,
    now() - state_change                                          AS time_in_current_state,
    left(query, 160)                                              AS current_or_last_query
FROM pg_stat_activity
WHERE application_name = :'target_application_name'
ORDER BY connection_age DESC;
""".strip("\n"),
               "A wide spread of connection_age values with many very-old connections suggests long-lived pooled connections (expected for a healthy pool); many very-young, rapidly cycling connections suggest the service is not pooling at all and opening a new connection per request.",
               related_scripts="../connection-pooling/README.md"),
]
