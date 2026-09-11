"""Workflow definitions: incident-response/ category (9 issue directories)."""
from __future__ import annotations

from typing import List

from . import sql_blocks as sb
from .helpers import (
    CONNECT_ONLY, PG_MONITOR, PG_MONITOR_PLUS_PGSS, md_script, sql_script,
)
from .model import Workflow

CATEGORY_SLUG = "incident-response"
CATEGORY_TITLE = "Incident Response"


def _wf(**kwargs) -> Workflow:
    kwargs.setdefault("category_slug", CATEGORY_SLUG)
    kwargs.setdefault("category_title", CATEGORY_TITLE)
    return Workflow(**kwargs)


# ---------------------------------------------------------------------------
# Safety labels used by the guarded .md remediation runbooks in this category.
# Incident response is the one category where the correct next action is
# frequently "end somebody else's session", so those actions are deliberately
# never shipped as executable .sql -- they live in .md runbooks that an
# operator must read, adapt, and run one statement at a time.
# ---------------------------------------------------------------------------
ELEVATED_RISK_SESSION = (
    "ELEVATED RISK -- MANUAL EXECUTION ONLY, CANCELS A STATEMENT OR ROLLS BACK THE "
    "TARGET TRANSACTION (read every warning in this file first)"
)
ELEVATED_RISK_CONFIG = (
    "ELEVATED RISK -- MANUAL EXECUTION ONLY, CHANGES CONFIGURATION THAT AFFECTS LIVE "
    "PRODUCTION TRAFFIC (read every warning in this file first)"
)

INCIDENT_OPERATOR_PRIVS = (
    "Reading the investigation output requires only `pg_monitor`. Ending another "
    "session additionally requires membership in `pg_signal_backend` (or, on "
    "Aurora, `rds_superuser`): a plain `pg_monitor` role can see the offending "
    "backend but cannot cancel or terminate it."
)
INCIDENT_TARGET_INSTANCE = (
    "The specific instance hosting the target backend -- `pg_cancel_backend()` / "
    "`pg_terminate_backend()` only affect backends on the instance you are "
    "currently connected to, so connect to the writer, or to the specific reader, "
    "where the session actually lives."
)


# ---------------------------------------------------------------------------
# Local composition helpers
# ---------------------------------------------------------------------------

def _combine(*parts: str) -> str:
    """Join several standalone read-only query bodies into one script."""
    return "\n\n".join(part.strip("\n") for part in parts)


def _pgss_guarded(body: str) -> str:
    """Wrap a pg_stat_statements query in an existence guard.

    The guard matters more here than anywhere else in the toolkit: incident
    scripts get run blind, by whoever is on call, against whichever cluster is
    burning -- a hard error because an extension is missing wastes the most
    expensive minutes of the whole incident.
    """
    return (
        "-- pg_stat_statements presence check. This script never creates the\n"
        "-- extension itself -- it only detects whether it is already available,\n"
        "-- so the script is safe to run blind during an incident.\n"
        "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements') AS pgss_available\n"
        "\\gset\n"
        "\n"
        "\\if :pgss_available\n"
        f"{body.strip()}\n"
        "\\else\n"
        "SELECT 'pg_stat_statements is not installed in this database, so statement-level '\n"
        "       'history is unavailable for this triage step. Ask an administrator to add '\n"
        "       'pg_stat_statements to shared_preload_libraries in the Aurora DB cluster '\n"
        "       'parameter group (a reboot is required for that change) and then install '\n"
        "       'the extension in a change-managed session -- an investigation script must '\n"
        "       'never do that for you mid-incident. Continue the checklist with the '\n"
        "       'remaining scripts; none of them depend on this extension.' AS notice;\n"
        "\\endif"
    )


def _aurora_guarded(body: str, notice: str) -> str:
    """Wrap an Aurora-only query in a catalog-only Aurora detection guard.

    The detection is a plain lookup in pg_proc -- it never calls the Aurora
    function itself -- so the script runs unchanged on community PostgreSQL
    (where it prints the notice) and on Aurora (where it runs the real query).
    """
    return (
        "-- Aurora detection by catalog lookup only. This never calls the\n"
        "-- Aurora-specific function unless that function actually exists, so the\n"
        "-- script is safe to run unchanged on community PostgreSQL too.\n"
        "SELECT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'aurora_replica_status') AS is_aurora\n"
        "\\gset\n"
        "\n"
        "\\if :is_aurora\n"
        f"{body.strip()}\n"
        "\\else\n"
        f"SELECT '{notice}' AS notice;\n"
        "\\endif"
    )


def _instance_identity_and_uptime() -> str:
    return r"""
-- "What am I actually connected to, and has it restarted?" -- the first
-- question of any availability incident. If this query returns a row at all,
-- the postmaster is up, listening, authenticating and serving queries, which
-- immediately rules out a large class of reported-as-database outages (DNS,
-- security group, endpoint misrouting, expired credentials, or an
-- application-side connection pool that is broken on its own).
--
-- instance_uptime is the highest-value column: an uptime shorter than the
-- reported incident duration means the instance restarted, or a failover
-- promoted a different writer, during the incident window -- which changes
-- the entire investigation.
SELECT
    current_database()                                          AS connected_database,
    current_user                                                AS connected_role,
    inet_server_addr()                                          AS server_address,
    inet_server_port()                                          AS server_port,
    pg_is_in_recovery()                                         AS is_reader_instance,
    pg_postmaster_start_time()                                  AS instance_start_time,
    now() - pg_postmaster_start_time()                          AS instance_uptime,
    now()                                                       AS server_time_now,
    current_setting('server_version')                           AS server_version;
""".strip("\n")


def _session_outcome_counters() -> str:
    return r"""
-- Per-database session outcome counters (PostgreSQL 14+, present on Aurora
-- PostgreSQL 17). These are cumulative since stats_reset, so read them as
-- "has this been happening at all", then re-run a minute later and diff the
-- values to get a rate:
--   * sessions_abandoned -- the client vanished without a clean disconnect
--     (application crash, pod eviction, network partition, or a load balancer
--     cutting an established connection on its idle timeout).
--   * sessions_fatal     -- the server ended the session with a FATAL error
--     (out of connection slots, authentication failure, backend crash).
--   * sessions_killed    -- the session was ended by an administrator command,
--     i.e. somebody has already run a termination during this incident.
-- Movement in sessions_killed that you cannot account for means another
-- responder is acting on the same cluster: find them before you both act.
SELECT
    datname,
    numbackends,
    sessions,
    sessions_abandoned,
    sessions_fatal,
    sessions_killed,
    xact_commit,
    xact_rollback,
    deadlocks,
    round(100.0 * sessions_abandoned / NULLIF(sessions, 0), 2)   AS pct_sessions_abandoned,
    round(100.0 * xact_rollback / NULLIF(xact_commit + xact_rollback, 0), 2) AS pct_rollback,
    stats_reset
FROM pg_stat_database
WHERE datname IS NOT NULL
ORDER BY sessions_abandoned DESC NULLS LAST;
""".strip("\n")


def _root_blockers_by_blast_radius() -> str:
    return r"""
-- Root-cause ranking for a lock storm: every backend that is blocking at
-- least one other backend, ranked by how many sessions it is directly
-- blocking. During a storm the raw pg_locks output is overwhelming -- this
-- collapses it to the handful of pids that actually matter.
--
-- Read blocker_is_itself_blocked_by_count first: a value of 0 means this
-- backend is a TRUE ROOT of the wait graph (nothing is blocking it, so it
-- will never clear by waiting for somebody else). A non-zero value means it
-- is a middle link in the chain, and resolving it achieves nothing because
-- the real root is further up.
SELECT
    b.blocking_pid,
    a.usename                                                   AS blocker_user,
    coalesce(NULLIF(a.application_name, ''), '(unset)')          AS blocker_application,
    a.datname                                                    AS blocker_database,
    a.state                                                      AS blocker_state,
    a.wait_event_type                                            AS blocker_wait_event_type,
    a.wait_event                                                 AS blocker_wait_event,
    now() - a.xact_start                                         AS blocker_txn_age,
    now() - a.state_change                                       AS blocker_time_in_state,
    count(*)                                                     AS directly_blocked_sessions,
    cardinality(pg_blocking_pids(b.blocking_pid))                AS blocker_is_itself_blocked_by_count,
    left(a.query, 200)                                           AS blocker_query
FROM (
    SELECT unnest(pg_blocking_pids(w.pid))                       AS blocking_pid
    FROM pg_stat_activity w
    WHERE cardinality(pg_blocking_pids(w.pid)) > 0
) b
JOIN pg_stat_activity a ON a.pid = b.blocking_pid
GROUP BY b.blocking_pid, a.usename, a.application_name, a.datname, a.state,
         a.wait_event_type, a.wait_event, a.xact_start, a.state_change, a.query
ORDER BY directly_blocked_sessions DESC, blocker_txn_age DESC NULLS LAST;
""".strip("\n")


def _target_backend_detail() -> str:
    return r"""
-- Full forensic detail for ONE specific backend, identified in the previous
-- script. Set :target_pid to the pid under investigation before running.
--
-- The default of 0 is never a real backend pid, so an unedited run returns
-- zero rows rather than reporting on the wrong session -- this script is
-- deliberately safe to run exactly as shipped.
\set target_pid 0
SELECT
    a.pid,
    a.datname,
    a.usename,
    coalesce(NULLIF(a.application_name, ''), '(unset)')          AS application_name,
    a.client_addr,
    a.backend_type,
    a.backend_start,
    a.xact_start,
    a.query_start,
    a.state_change,
    a.state,
    a.wait_event_type,
    a.wait_event,
    a.backend_xid,
    a.backend_xmin,
    now() - a.query_start                                        AS query_runtime,
    now() - a.xact_start                                         AS txn_runtime,
    cardinality(pg_blocking_pids(a.pid))                         AS is_blocked_by_count,
    pg_blocking_pids(a.pid)                                      AS is_blocked_by_pids,
    (
        SELECT count(*)
        FROM pg_stat_activity w
        WHERE a.pid = ANY (pg_blocking_pids(w.pid))
    )                                                            AS sessions_this_backend_blocks,
    a.query                                                      AS full_query_text
FROM pg_stat_activity a
WHERE a.pid = :target_pid;
""".strip("\n")


def _idle_sessions_by_age() -> str:
    return r"""
-- Plain 'idle' sessions (connected, but NOT inside a transaction) ranked by
-- how long they have been idle. These are the cheapest connection slots to
-- reclaim during connection exhaustion: an idle session holds no locks, no
-- snapshot and no in-flight work, so ending it loses nothing except the TCP
-- connection itself, which a healthy pool re-establishes transparently.
--
-- Contrast with 'idle in transaction' sessions (see the dedicated script in
-- this workflow): those DO hold a snapshot and possibly locks, and ending one
-- rolls back whatever its transaction had already done.
\set top_n 50
SELECT
    pid,
    datname,
    usename,
    coalesce(NULLIF(application_name, ''), '(unset)')            AS application_name,
    client_addr,
    backend_start,
    state_change,
    now() - state_change                                         AS idle_duration,
    now() - backend_start                                        AS connection_age,
    left(query, 120)                                             AS last_statement
FROM pg_stat_activity
WHERE state = 'idle'
  AND pid <> pg_backend_pid()
ORDER BY idle_duration DESC
LIMIT :top_n;
""".strip("\n")


def _workload_by_application_with_session_age() -> str:
    return r"""
-- Current workload attributed to the service that generated it, including
-- when each group's sessions were established. After a deployment this is the
-- fastest way to watch the new fleet arrive: a cluster of sessions whose
-- newest_session_started (and often oldest_session_started) lines up with the
-- rollout timestamp is the newly deployed replica set, and comparing its
-- active_count / blocked_count against the services that did NOT change tells
-- you within seconds whether the deployment is the cause or a victim.
--
-- This depends on every service actually setting application_name; a large
-- '(unset)' group makes the attribution useless, so fix that in the affected
-- service's connection string as a follow-up action.
SELECT
    coalesce(NULLIF(a.application_name, ''), '(unset)')          AS application_name,
    a.usename,
    a.datname,
    count(*)                                                     AS session_count,
    count(*) FILTER (WHERE a.state = 'active')                   AS active_count,
    count(*) FILTER (WHERE a.state = 'idle')                     AS idle_count,
    count(*) FILTER (WHERE a.state = 'idle in transaction')      AS idle_in_txn_count,
    count(*) FILTER (WHERE cardinality(pg_blocking_pids(a.pid)) > 0) AS blocked_count,
    min(a.backend_start)                                         AS oldest_session_started,
    max(a.backend_start)                                         AS newest_session_started,
    max(now() - a.query_start) FILTER (WHERE a.state = 'active') AS longest_active_query,
    max(now() - a.xact_start)                                    AS longest_open_transaction
FROM pg_stat_activity a
WHERE a.pid <> pg_backend_pid()
  AND a.backend_type = 'client backend'
GROUP BY 1, 2, 3
ORDER BY session_count DESC;
""".strip("\n")


def _role_and_database_setting_overrides() -> str:
    return r"""
-- Role-level and database-level GUC overrides (pg_db_role_setting). This is
-- the settings layer pg_settings does NOT show you: pg_settings reports what
-- YOUR session resolved to, while this shows the per-role / per-database
-- ALTER ROLE ... SET and ALTER DATABASE ... SET overrides that apply to other
-- roles -- for example statement_timeout = 0 (no timeout) applied to a
-- reporting role, or statement_timeout = 2s applied to the trading API role.
--
-- During a timeout incident this answers "which timeout is the application
-- actually hitting" far faster than reading application configuration
-- repositories, and it frequently explains why one service times out while
-- another, running the same query, does not.
SELECT
    coalesce(r.rolname, '(all roles)')                           AS role_name,
    coalesce(d.datname, '(all databases)')                       AS database_name,
    s.setconfig                                                  AS applied_settings
FROM pg_db_role_setting s
LEFT JOIN pg_roles r ON r.oid = s.setrole
LEFT JOIN pg_database d ON d.oid = s.setdatabase
ORDER BY database_name, role_name;
""".strip("\n")


def _cancel_vs_terminate_section() -> str:
    """Shared, deliberately repeated explanation of the two session-ending
    functions. Duplicated into each remediation runbook on purpose: an on-call
    engineer must never have to open a second file to find out what the
    statement they are about to run actually does."""
    return (
        "## Cancel vs. terminate -- understand both before you type either\n"
        "\n"
        "| Function | Signal | Effect | Client sees | Uncommitted work |\n"
        "|---|---|---|---|---|\n"
        "| `pg_cancel_backend(pid)` | SIGINT | Aborts the **currently running statement** only. The connection survives and the surrounding transaction stays open, moving to `idle in transaction (aborted)` until the client issues `COMMIT` or `ROLLBACK`. | `ERROR: canceling statement due to user request` (SQLSTATE `57014`) | Only the cancelled statement is undone. Earlier statements in the same open transaction stay pending until the client ends the transaction. |\n"
        "| `pg_terminate_backend(pid)` | SIGTERM | Kills the **entire backend and its connection**. | `FATAL: terminating connection due to administrator command` (SQLSTATE `57P01`), then a dropped connection | The whole open transaction is rolled back. Everything it did since `BEGIN` and had not committed is lost. |\n"
        "\n"
        "Both functions return `true` when the signal was *delivered* -- not when the\n"
        "target actually stopped. Always re-run the investigation script afterwards to\n"
        "confirm the session is really gone: a backend inside an uninterruptible\n"
        "operation can ignore a cancel entirely, and a terminated backend that is still\n"
        "rolling back a large transaction stays visible for as long as the rollback\n"
        "takes (which, for a long bulk write, can be minutes).\n"
        "\n"
        "**Always try `pg_cancel_backend()` first.** It is strictly less disruptive, it\n"
        "resolves the large majority of incidents, and if it fails you can still escalate\n"
        "to a terminate seconds later. There is no path back from a terminate.\n"
        "\n"
        "### Financial-write safety gate (non-negotiable)\n"
        "\n"
        "Before terminating any backend whose statement touches a financial table\n"
        "(`ledger_entries`, `wallets`, `withdrawals`, `deposits`, `trades`, `orders`,\n"
        "settlement or position tables), you must have all four of the following:\n"
        "\n"
        "1. The full statement text and the owning service, from the investigation scripts\n"
        "   in this workflow -- never from memory or from a screenshot in the channel.\n"
        "2. Explicit confirmation from that service's on-call owner that rolling the\n"
        "   transaction back is safe and that the operation is **idempotent on retry**. A\n"
        "   half-applied withdrawal or a double-credited deposit is a far worse incident\n"
        "   than the latency you are trying to fix.\n"
        "3. A second engineer on the call who reads the pid back to you before you run it.\n"
        "   Operating systems reuse pids; a stale pid from a five-minute-old snapshot can\n"
        "   terminate an entirely innocent session.\n"
        "4. The action, the pid, the statement text, the approver and the timestamp posted\n"
        "   in the incident channel at the moment you run it -- for the post-incident\n"
        "   review, and for any reconciliation of the affected accounts afterwards.\n"
        "\n"
        "Never end a backend whose `backend_type` is not `client backend` (for example\n"
        "`autovacuum worker`, `walsender`, `checkpointer`, or an Aurora-internal backend).\n"
        "Terminating background machinery does not fix an application incident and can\n"
        "make the cluster's state materially worse.\n"
    )


WORKFLOWS: List[Workflow] = []

# ---------------------------------------------------------------------------
# 1. database-unavailable
# ---------------------------------------------------------------------------
WORKFLOWS.append(_wf(
    slug="database-unavailable",
    title="Database Unavailable",
    summary=(
        "Services report that the database is down: connections are refused, "
        "time out, or fail instantly, and trading, deposits, withdrawals and "
        "settlement are failing across the board. This workflow covers the "
        "first five minutes of that incident -- establishing whether the "
        "database is genuinely unavailable, unavailable only to some callers, "
        "or completely healthy behind a broken connectivity or pooling layer, "
        "before anybody reaches for a failover or a restart."
    ),
    symptoms=[
        "Application logs full of `connection refused`, `could not connect to server`, or connection-timeout errors against the cluster endpoint.",
        "`FATAL: sorry, too many clients already` returned to new connections while existing sessions keep working normally.",
        "Health checks for order entry, wallet services and the matching engine failing simultaneously.",
        "The writer endpoint is unreachable while the reader endpoint still answers, or the reverse.",
        "A CloudWatch DatabaseConnections cliff, or an instance-level availability event on the cluster.",
    ],
    business_impact=[
        "Order entry, cancellation and matching stop entirely -- customers cannot exit positions during a market move, which is simultaneously a financial, reputational and regulatory event.",
        "Deposits and withdrawals queue or fail, so customer funds appear stuck, driving immediate support escalation and, past a short window, reporting obligations.",
        "Settlement, risk and compliance jobs miss their windows, creating reconciliation work that outlives the outage itself.",
        "A misdiagnosed outage -- failing over a database that was actually healthy -- adds a second, self-inflicted outage window on top of the first.",
    ],
    root_causes=[
        "Connection-layer: connection slots exhausted (`max_connections` reached), so the database is perfectly healthy but refuses every new session.",
        "Connection-layer: the pooler (RDS Proxy / PgBouncer) or its host is down, leaving the database healthy but unreachable from the application's point of view.",
        "Network/infrastructure: a security group, subnet, route or DNS change sending traffic to the wrong or a stale endpoint, often after a failover.",
        "Cluster-level: an Aurora failover in progress, where the writer endpoint briefly resolves to an instance that is not yet accepting writes.",
        "Instance-level: the instance restarted (out-of-memory kill, storage event, maintenance action), dropping every pre-existing connection at once.",
        "Workload-level: a lock storm or runaway query saturating the instance so completely that new connections cannot be serviced inside the client's timeout.",
        "Authentication: credential rotation or a role change causing every new connection to fail authentication while already-established sessions survive.",
    ],
    investigation_strategy=[
        "Try to connect at all, from a path that does not traverse the application's pooler. If your psql session connects, the postmaster is alive, and that single fact eliminates most 'database is down' hypotheses immediately.",
        "Confirm which instance answered and how long it has been up -- an uptime shorter than the incident window means a restart or failover has already happened.",
        "Confirm the cluster role and replica topology: are you on the writer, and are the readers healthy and in sync?",
        "Check connection-slot saturation, which is the single most common cause of a total-outage report against an otherwise perfectly healthy Aurora cluster.",
        "Check the session outcome counters for a spike in fatal, abandoned or killed sessions, which separates a server-side refusal from a client-side disconnect storm.",
        "Check for a lock storm or very old transactions paralysing the instance, which makes a healthy database indistinguishable from a dead one.",
        "Only after all of the above, consider mitigation: reclaiming slots, restarting the pooler, or escalating a failover decision.",
    ],
    prerequisites=[
        "A direct psql path to the cluster that does NOT go through the application's pooler. During a pooler outage this is the only way to reach the database, so it must be established and tested long before the incident.",
        "`pg_monitor` role membership for the connecting user.",
        "AWS Console/CLI access for cluster events, instance status, and the CloudWatch DatabaseConnections and CPUUtilization metrics for the cluster.",
        "Knowledge of which endpoint each service uses (cluster writer endpoint, reader endpoint, custom endpoint, or a pooler address).",
    ],
    interpretation_guide=[
        "If script 01 returns a row, the database is UP. Say so explicitly in the incident channel: it redirects the entire response from 'restore the database' to 'restore access to the database', which are completely different actions with completely different risk profiles.",
        "`instance_uptime` shorter than the incident duration means the instance restarted or failed over. Stop looking for a live workload cause and pivot to the failover investigation.",
        "`is_reader_instance = true` when you expected the writer means the writer endpoint resolved to a reader (failover in progress, or a stale DNS cache in the client). Writes fail with a read-only transaction error while the cluster itself is entirely healthy.",
        "`pct_utilized` at or near 100% in script 03 means the database is refusing new connections while serving existing ones perfectly -- that is connection exhaustion, not an outage.",
        "A large `sessions_abandoned` jump with normal `sessions_fatal` points at the client side: an application crash-loop, pod evictions, or a load balancer cutting idle connections.",
        "A large `sessions_fatal` jump points at the server side: out of slots, authentication failures, or backends being terminated.",
    ],
    remediation_immediate=[
        "If connection slots are exhausted, reclaim slots by ending long-idle sessions per the guarded runbook in this workflow, and in the same minute tell the owning service to reduce its pool size -- reclaiming slots without fixing the source just refills them within seconds.",
        "If the pooler is the failure point, either fail application traffic over to the direct cluster endpoint (only if the connection count allows it) or restart the pooler, per the runbook.",
        "If a failover is in progress, do nothing to the database. Let the endpoint converge and confirm that applications are retrying with backoff rather than hot-looping, which is what turns a 30-second failover into a connection storm.",
        "If a lock storm or runaway query is saturating the instance, switch to the lock-storm or runaway-query workflow in this category -- the unavailability is a symptom, not the cause.",
    ],
    remediation_short_term=[
        "Right-size connection pools against the instance's actual `max_connections`, with a documented per-service budget whose total leaves real headroom.",
        "Put a pooler (RDS Proxy, or PgBouncer in transaction mode) in front of every service with high connection churn, so a service restart cannot storm the database with fresh connections.",
        "Set `idle_in_transaction_session_timeout` and a sane `statement_timeout` per application role so no single misbehaving client can hold slots indefinitely.",
        "Add connection retry with exponential backoff and jitter to every service, so a brief failover does not become a self-inflicted connection storm.",
    ],
    remediation_long_term=[
        "Reserve connection headroom explicitly for operators: a break-glass role and connection path that application traffic never uses, so responders can always get in.",
        "Run regular failover game days, so application behaviour during an endpoint change is a known quantity instead of a discovery made mid-incident.",
        "Build a cluster availability dashboard combining DatabaseConnections, CPUUtilization, writer/reader role and pooler health, so 'is the database down' is answered by a graph in seconds rather than by an investigation.",
    ],
    production_safety=[
        "Scripts 01-05 are strictly read-only and safe to run during a total outage -- they read catalogs and statistics views only, and take no locks beyond brief catalog lookups.",
        "Script 06 is a guarded manual runbook that can end other sessions; read it fully before executing any statement in it.",
        "Never restart or fail over a cluster as a first response. If the database is answering queries, a failover converts a partial incident into a guaranteed full write-outage window.",
    ],
    escalation_criteria=[
        "You cannot connect at all from a known-good direct path -- escalate immediately to AWS support and database engineering leadership, and start the disaster-recovery assessment in parallel.",
        "The instance restarted with no explanation in the cluster events -- escalate to database engineering, because an unexplained restart tends to recur.",
        "Deposits or withdrawals have been failing for more than a few minutes -- escalate to the treasury and compliance on-call in parallel with the technical fix, because customer-funds visibility carries its own reporting obligations.",
        "Restoring access requires a failover or an instance-class change beyond on-call authority.",
    ],
    related_issues=[
        "../production-triage/README.md",
        "../connection-exhaustion/README.md",
        "../lock-storm/README.md",
        "../../connections/connection-exhaustion/README.md",
        "../../replication-and-ha/failover-investigation/README.md",
        "../../disaster-recovery/README.md",
    ],
    aurora_notes=[
        "Aurora's writer endpoint is a DNS record that moves during a failover. A client with a cached DNS entry (a JVM with an infinite DNS TTL is the classic case) keeps connecting to the old writer, which is now a reader, and every write fails with a read-only transaction error while the cluster is perfectly healthy -- always confirm `pg_is_in_recovery()` on the connection that is actually failing.",
        "`max_connections` on Aurora is derived from the instance class's memory through the parameter-group formula rather than freely chosen, so 'just raise max_connections' is not a valid immediate mitigation: it needs a parameter-group change and, in most cases, a restart.",
        "Aurora cluster events (failover, restart, storage, maintenance) are visible in the RDS console and via `aws rds describe-events`, not in any SQL catalog. Pull them in parallel with these scripts, because they frequently contain the actual answer.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_instance_identity_and_uptime",
               "Confirms the database is reachable at all, and identifies exactly which instance answered, its role, and how long it has been running.",
               _instance_identity_and_uptime(),
               "A returned row proves the postmaster is up and serving queries -- announce that immediately. Then compare instance_uptime against the incident start: a shorter uptime means a restart or failover already happened, and is_reader_instance = true when you expected a writer means the endpoint resolved to the wrong instance.",
               required_privileges=CONNECT_ONLY,
               related_scripts="02_cluster_role_and_replica_status.sql",
               table_purpose="Proves reachability and identifies the answering instance, its role and uptime."),
    sql_script("02", "02_cluster_role_and_replica_status",
               "Establishes cluster topology: whether this connection is on the writer or a reader, and the Aurora-reported status and lag of every instance in the cluster.",
               _combine(
                   sb.cluster_recovery_role(),
                   _aurora_guarded(
                       sb.aurora_replica_status(),
                       "aurora_replica_status() is not present on this server, so this is not an Aurora "
                       "PostgreSQL cluster. Use pg_stat_replication on the primary instead to review "
                       "streaming replication status for this topology.",
                   ),
               ),
               "If the writer endpoint landed you on a reader, writes fail while reads succeed -- that is a failover or DNS-cache problem, not an outage. Replica lag climbing on every reader at once points at the writer being saturated rather than at the readers themselves.",
               related_scripts="01_instance_identity_and_uptime.sql, 03_connection_slot_saturation.sql",
               table_purpose="Writer/reader role plus Aurora cluster-wide replica status and lag."),
    sql_script("03", "03_connection_slot_saturation",
               "Checks whether the cluster is refusing new connections because its connection slots are full -- the most common cause of a total-outage report against a healthy database.",
               _combine(sb.max_connections_headroom(), sb.connections_by_state()),
               "pct_utilized at or above roughly 95% means new connections are being refused with 'too many clients' while existing sessions run normally. A state breakdown dominated by 'idle' means a pool is hoarding slots it is not using; dominated by 'idle in transaction' means an application is leaking open transactions; dominated by 'active' means genuine load.",
               related_scripts="04_session_outcome_counters.sql, ../connection-exhaustion/README.md",
               table_purpose="Connection headroom against max_connections, broken down by state."),
    sql_script("04", "04_session_outcome_counters",
               "Distinguishes server-side refusals from client-side disconnects using the per-database session outcome counters.",
               _session_outcome_counters(),
               "A spike concentrated in sessions_abandoned means clients are disappearing (crash-loop, pod eviction, network drop) and this is an application-side incident. A spike in sessions_fatal means the server is rejecting or ending sessions. Any movement in sessions_killed you did not cause means another responder is already acting on this cluster -- coordinate before you both act.",
               related_scripts="05_blocked_and_stuck_sessions.sql",
               table_purpose="Abandoned / fatal / killed session counters per database."),
    sql_script("05", "05_blocked_and_stuck_sessions",
               "Checks whether the instance is alive but effectively paralysed by blocking or by very old open transactions.",
               _combine(sb.blocked_sessions(), sb.long_running_transactions()),
               "A large set of blocked sessions behind a small set of blockers means this is a lock storm wearing an outage costume -- switch to the lock-storm workflow. A transaction open for longer than the incident window is a strong candidate for the original trigger.",
               related_scripts="../lock-storm/README.md, ../../concurrency-and-locking/blocked-queries/README.md",
               table_purpose="Blocked-session pileup plus the oldest open transactions."),
    md_script("06", "06_availability_mitigation_actions",
              "Guarded runbook for the small set of actions that can restore access during an availability incident: reclaiming connection slots, ending a paralysing session, and deciding whether a failover is justified.",
              (
                  "## Use this file only after scripts 01-05\n"
                  "\n"
                  "Every action below is written as: the precondition that must be true, the\n"
                  "statement, and what it costs if you are wrong. If the precondition from the\n"
                  "read-only scripts is not satisfied, the action is not the right one, and taking\n"
                  "it anyway during an outage reliably makes the incident longer.\n"
                  "\n"
                  + _cancel_vs_terminate_section() +
                  "\n"
                  "## Action A -- reclaim connection slots\n"
                  "\n"
                  "*Precondition: script 03 shows pct_utilized near 100%.*\n"
                  "\n"
                  "Reclaim the cheapest slots first: sessions that are plain `idle`, not `idle in\n"
                  "transaction`, and idle for far longer than any plausible in-flight request.\n"
                  "\n"
                  "Step 1 -- list the candidates and actually read them (read-only, safe):\n"
                  "\n"
                  "```sql\n"
                  "SELECT pid, usename, application_name, client_addr,\n"
                  "       now() - state_change AS idle_duration\n"
                  "FROM pg_stat_activity\n"
                  "WHERE state = 'idle'\n"
                  "  AND backend_type = 'client backend'\n"
                  "  AND pid <> pg_backend_pid()\n"
                  "  AND now() - state_change > interval '10 minutes'\n"
                  "ORDER BY idle_duration DESC;\n"
                  "```\n"
                  "\n"
                  "Step 2 -- end them **one pid at a time**, reading each pid back to a second\n"
                  "engineer first:\n"
                  "\n"
                  "```sql\n"
                  "SELECT pg_terminate_backend(<pid from step 1>);\n"
                  "```\n"
                  "\n"
                  "Cost if you are wrong: a healthy client loses a pooled connection and opens a\n"
                  "new one. This is the lowest-risk action in the entire category -- but it is a\n"
                  "treatment, not a cure. Slots refill within seconds unless the owning service\n"
                  "reduces its pool size at the same time, so raise that with the service owner\n"
                  "immediately.\n"
                  "\n"
                  "Never write a single statement that terminates every matching session at once\n"
                  "during an incident. A set-returning termination is exactly how a connection\n"
                  "exhaustion incident becomes a fleet-wide application restart storm.\n"
                  "\n"
                  "## Action B -- end a session that is paralysing the instance\n"
                  "\n"
                  "*Precondition: script 05 shows one blocker with many waiters behind it.*\n"
                  "\n"
                  "Cancel first:\n"
                  "\n"
                  "```sql\n"
                  "SELECT pg_cancel_backend(<root blocker pid from script 05>);\n"
                  "```\n"
                  "\n"
                  "Re-run script 05. If the wait graph has not cleared within about 15 seconds and\n"
                  "the financial-write safety gate above has been satisfied, escalate:\n"
                  "\n"
                  "```sql\n"
                  "SELECT pg_terminate_backend(<root blocker pid from script 05>);\n"
                  "```\n"
                  "\n"
                  "## Action C -- pooler failure\n"
                  "\n"
                  "*Precondition: the database answers your direct psql session, but application\n"
                  "traffic still cannot reach it.*\n"
                  "\n"
                  "This is an application-platform action, not a database one. Confirm with the\n"
                  "platform on-call before doing either of these:\n"
                  "\n"
                  "* Restart the pooler (the RDS Proxy target group, or the PgBouncer fleet). Every\n"
                  "  in-flight transaction through that pooler is lost -- for an exchange, that\n"
                  "  means in-flight order and wallet writes fail and must be retried by the client.\n"
                  "* Point services temporarily at the direct cluster endpoint. Only after checking\n"
                  "  script 03: bypassing the pooler multiplies the connection count by whatever the\n"
                  "  pooler was multiplexing, and can take the database from healthy to\n"
                  "  slot-exhausted in a single deployment.\n"
                  "\n"
                  "## Action D -- failover\n"
                  "\n"
                  "*Precondition: everything above is exhausted.*\n"
                  "\n"
                  "A failover is not an action you take from psql, and it is never a first response.\n"
                  "It costs a guaranteed write-unavailability window of roughly 30-60 seconds plus\n"
                  "application reconnect time, and it discards the buffer cache on the promoted\n"
                  "instance, so the first minutes after promotion are measurably slower for exactly\n"
                  "the workload you are trying to rescue.\n"
                  "\n"
                  "Justify a failover only when the writer instance is confirmed unresponsive to new\n"
                  "connections from a direct path, or when an AWS cluster event shows a hardware or\n"
                  "storage problem on the current writer. It requires the approval named in your\n"
                  "escalation policy and should be executed through the RDS console or CLI by the\n"
                  "person holding that authority. See `../../replication-and-ha/failover-investigation/README.md`\n"
                  "and `../../disaster-recovery/README.md`.\n"
                  "\n"
                  "## After the incident\n"
                  "\n"
                  "Record every pid you ended, why, who approved it, and the exact timestamps. For\n"
                  "any terminated session that was mid-write on a financial table, hand the list to\n"
                  "the owning team for reconciliation before the incident is closed.\n"
              ),
              "Read this file top to bottom before executing anything in it. Each action names the script output that must be true for it to be the correct action; if that precondition is absent, the action is wrong and will extend the incident.",
              safety=ELEVATED_RISK_SESSION,
              expected_impact="Varies by action: ending an idle session drops one pooled connection; terminating an active session rolls its transaction back; a pooler restart or a failover causes a short, deliberate outage window.",
              required_privileges=INCIDENT_OPERATOR_PRIVS,
              prerequisites="Scripts 01-05 completed, the precondition for the chosen action confirmed, and a second engineer on the call to verify pids.",
              execution_location=INCIDENT_TARGET_INSTANCE,
              expected_runtime="Seconds per statement, though a terminated transaction can take minutes to finish rolling back.",
              related_scripts="03_connection_slot_saturation.sql, 05_blocked_and_stuck_sessions.sql",
              table_purpose="Guarded actions: reclaim slots, end a paralysing session, pooler restart, failover decision."),
]

# ---------------------------------------------------------------------------
# 2. sudden-latency-spike
# ---------------------------------------------------------------------------
WORKFLOWS.append(_wf(
    slug="sudden-latency-spike",
    title="Sudden Latency Spike",
    summary=(
        "Database response times jumped sharply and recently -- p99 order "
        "placement, balance reads or ledger writes went from milliseconds to "
        "seconds within minutes -- without any obvious outage. This workflow "
        "is the fast triage that separates the four candidate causes "
        "(blocking, a plan or workload change, resource saturation, or "
        "pressure from checkpoint/IO/temp activity) quickly enough to act on "
        "the answer, rather than the deep single-query analysis that belongs "
        "in the performance category."
    ),
    symptoms=[
        "p95/p99 latency for database calls steps up sharply at an identifiable minute rather than degrading gradually.",
        "Order placement and cancellation acknowledgements slow down while throughput stays flat or falls.",
        "Active session count in pg_stat_activity climbs because each request now holds its connection longer.",
        "Aurora Performance Insights shows Average Active Sessions rising with a visible change in the wait-event mix.",
        "Market-data or risk consumers start lagging because their reads now queue behind slower writes.",
    ],
    business_impact=[
        "Latency on the order path directly degrades fill quality; during volatile markets a few hundred extra milliseconds is the difference between a filled and a missed order, and customers notice immediately.",
        "Slower ledger and wallet writes push deposit and withdrawal confirmations past their SLA, generating support volume and, if sustained, regulatory attention.",
        "Upstream services with their own timeouts begin failing and retrying, which adds load to the very database that is already slow -- latency spikes are self-amplifying if not cut quickly.",
    ],
    root_causes=[
        "Concurrency: a new blocking chain, so most of the added latency is lock wait rather than work.",
        "Workload: a traffic surge (market event, a newly enabled feature, a retry storm from an upstream service) pushing the instance past its comfortable concurrency point.",
        "Plan/statistics: a plan flipped after an autoanalyze or a data-distribution change, and one hot statement now costs an order of magnitude more.",
        "Resource: CPU or IO saturation from a heavy batch job, a large index build, or aggressive autovacuum running during peak trading hours.",
        "Memory: queries spilling sorts and hashes to temp files because work_mem is too small for the new data volume.",
        "Checkpoint/WAL: a burst of write activity forcing frequent checkpoints and stalling foreground writes.",
        "Replication: readers falling behind, so read traffic routed to them returns stale or slow results and the application retries against the writer.",
    ],
    investigation_strategy=[
        "Take a single broad activity snapshot first -- how many sessions, in what states, and how long has the longest one been running.",
        "Read the wait-event mix immediately after. This is the fastest branch point in the whole workflow: Lock waits mean blocking, IO waits mean resource pressure, and an absence of waits with high active counts means genuine CPU-bound work.",
        "List the longest-running active queries to see whether one statement shape dominates the new latency.",
        "Check for a blocking chain, because a single blocker explains a cluster-wide latency step change more often than any other single cause.",
        "Check checkpoint, IO and temp-file pressure, which explains latency that appears in write paths without any corresponding blocking.",
        "Compare current statement timing against pg_stat_statements history to identify the specific statements whose mean time has moved.",
        "Decide and act: unblock, shed or cancel the offending work, or escalate to the matching deep-dive workflow.",
    ],
    prerequisites=[
        "`pg_monitor` role membership.",
        "`pg_stat_statements` for script 06 (the workflow still functions without it -- the script prints a notice rather than failing).",
        "A latency baseline you can compare against: yesterday's p99 at the same time of day, not a vague sense of normal.",
        "The deployment and market-event timeline for the last hour, so correlation is possible at all.",
    ],
    interpretation_guide=[
        "Wait events are the branch point. A Lock-dominated mix means go straight to lock-storm; an IO-dominated mix means resource pressure; LWLock or IPC waits suggest internal contention and usually accompany a concurrency level the instance cannot absorb.",
        "Many active sessions with NULL wait events and short individual runtimes is a throughput problem, not a single-query problem -- the instance is doing a lot of small work well, just more of it than it has capacity for.",
        "One statement shape appearing repeatedly in the long-running list with a mean time far above its historical value is a plan regression until proven otherwise.",
        "A jump in temp_bytes together with slow sorts points at work_mem, and it is usually triggered by data growth rather than by a code change -- the query did not change, the volume did.",
        "A high pct_forced_checkpoints means write volume is outrunning max_wal_size, and foreground writes are paying for it.",
        "If every signal here looks normal, the latency is probably not in the database: check the pooler, the network path and the application's own garbage collection before continuing here.",
    ],
    remediation_immediate=[
        "If blocking dominates, resolve the root blocker using the lock-storm workflow -- that single action usually restores latency across every affected service at once.",
        "If one runaway statement dominates, cancel it per the runaway-query runbook after confirming ownership.",
        "If load is legitimately elevated, shed or throttle the least business-critical traffic first (reporting, analytics, backfills) rather than degrading the order path for everyone.",
        "If a batch job or index build is competing with peak traffic, pause or cancel it -- it can be rerun in a quiet window; the trading day cannot.",
    ],
    remediation_short_term=[
        "Refresh statistics on the specific tables backing the regressed statements rather than analysing everything blindly.",
        "Add or correct the index that the regressed statement needs, following the schema-changes concurrent build pattern.",
        "Raise work_mem for the specific role running the spilling workload rather than globally, so a per-connection increase cannot exhaust instance memory.",
        "Move reporting and analytical consumers to the reader endpoint so they cannot contend with the order path again.",
    ],
    remediation_long_term=[
        "Add latency SLOs per query shape with alerting on step changes, so the next spike is detected by monitoring rather than by customers.",
        "Introduce plan-stability checks in CI for the handful of statements on the trading and settlement hot path.",
        "Schedule batch, backfill and index maintenance work in explicit low-volume windows enforced by tooling, not by convention.",
    ],
    production_safety=[
        "Scripts 01-06 are read-only and safe to run repeatedly during the spike; taking two snapshots a minute apart is often more informative than one.",
        "Script 07 is a guarded manual runbook whose actions cancel work or change live configuration -- read it fully first.",
        "Do not restart the instance or fail over to 'clear' a latency spike. It discards the buffer cache and makes latency worse for several minutes, on top of the outage the failover itself causes.",
    ],
    escalation_criteria=[
        "Latency stays elevated for more than 15 minutes with customer-visible impact on the order or withdrawal path.",
        "The spike coincides with a deployment that cannot be rolled back without a data migration -- involve the deploying team and database engineering jointly, immediately.",
        "The dominant wait events are Aurora-internal (IO or IPC waits with no application-side explanation) -- open an AWS support case in parallel with continuing the investigation.",
        "Latency degradation is accompanied by rising replica lag on every reader, which suggests a writer-side saturation problem with cluster-wide reach.",
    ],
    related_issues=[
        "../production-triage/README.md",
        "../lock-storm/README.md",
        "../runaway-query/README.md",
        "../application-timeouts/README.md",
        "../../performance/high-cpu/README.md",
        "../../concurrency-and-locking/blocked-queries/README.md",
    ],
    aurora_notes=[
        "Aurora's storage layer means write latency is a network round trip to a quorum of storage nodes rather than a local disk flush, so a latency spike on writes can come from the storage fleet rather than from anything visible in the instance's own catalogs -- correlate with the CloudWatch WriteLatency and DiskQueueDepth metrics before concluding the cause is in your workload.",
        "Performance Insights retains per-second wait-event history, so it can show you the exact minute the wait-event mix changed. Reconstructing that from pg_stat_activity snapshots is far slower and much less precise.",
        "Aurora reader instances serve reads from the same storage volume as the writer, so a latency spike caused by storage-layer pressure appears on readers and the writer simultaneously -- that pattern rules out most query-level explanations immediately.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_activity_overview",
               "Broad session/state snapshot to size the spike before drilling into any single cause.",
               sb.activity_overview(),
               "Compare session_count and longest_query_runtime against your normal baseline for this time of day. A high active count with short runtimes is a throughput problem; a moderate active count with very long runtimes is a small number of expensive statements, and the two need opposite responses.",
               related_scripts="02_wait_event_mix.sql",
               table_purpose="Session counts by database, state and wait-event type."),
    sql_script("02", "02_wait_event_mix",
               "Reads the current wait-event distribution -- the fastest branch point for deciding which cause to pursue.",
               sb.wait_events_summary(),
               "Lock-dominated means go to lock-storm. IO-dominated means resource or checkpoint pressure (script 05). LWLock or IPC means internal contention from too much concurrency. An empty or tiny wait-event set with many active sessions means genuinely CPU-bound work, so use the high-cpu checklist in this category.",
               related_scripts="03_longest_active_queries.sql, ../lock-storm/README.md",
               table_purpose="Wait-event distribution with the PG17 pg_wait_events descriptions."),
    sql_script("03", "03_longest_active_queries",
               "Lists the currently active queries running longest, to see whether one statement shape dominates the new latency.",
               sb.active_long_running_queries(),
               "Repetition is the signal: the same normalized statement appearing many times with a runtime far above its usual profile is a regressed statement. A single unique long query alongside otherwise-normal traffic is a runaway query instead, and belongs in that workflow.",
               related_scripts="04_blocking_snapshot.sql, ../runaway-query/README.md",
               table_purpose="Active queries above the runtime threshold, ranked by runtime."),
    sql_script("04", "04_blocking_snapshot",
               "Checks whether the added latency is simply lock wait, which is the most common single explanation for a cluster-wide step change.",
               sb.blocked_sessions(),
               "Any meaningful number of blocked sessions makes this a blocking incident first and a performance incident second. Note the blocking_pids and move to lock-storm; tuning anything else while a blocker is live is wasted effort.",
               related_scripts="../lock-storm/README.md, ../../concurrency-and-locking/blocked-queries/README.md",
               table_purpose="Sessions currently blocked, with their blocking pids."),
    sql_script("05", "05_checkpoint_io_and_temp_pressure",
               "Checks checkpoint frequency, per-backend-type IO and temp-file volume -- the resource-pressure explanations for latency that has no blocking behind it.",
               _combine(sb.checkpoint_activity(), sb.pg_stat_io_summary(), sb.temp_file_usage_by_database()),
               "A high pct_forced_checkpoints means write volume is outrunning max_wal_size and foreground writes are stalling. Large derived read volume attributed to client backends means queries are missing the buffer cache. A climbing temp_bytes means sorts and hashes are spilling to disk, which points at work_mem or at stale statistics producing bad row estimates.",
               related_scripts="06_statement_timing_shift.sql",
               table_purpose="Checkpoint, IO and temp-file pressure indicators in one snapshot."),
    sql_script("06", "06_statement_timing_shift",
               "Compares current statement timings against pg_stat_statements history to find the specific statements whose cost has moved.",
               _pgss_guarded(sb.pgss_top_by_mean_time()),
               "A statement whose mean_exec_time is far above its historical norm, with a large stddev_exec_time, is either contended or parameter-sensitive; a uniformly elevated mean with a small stddev is a plan regression. Capture the queryid before you remediate -- it is the handle every follow-up workflow needs.",
               required_privileges=PG_MONITOR_PLUS_PGSS,
               prerequisites="pg_stat_statements installed in the current database; the script prints a notice and exits cleanly if it is not.",
               related_scripts="../../performance/high-cpu/README.md",
               table_purpose="Slowest statements by mean execution time from pg_stat_statements."),
    md_script("07", "07_latency_mitigation_actions",
              "Guarded runbook for the actions that actually cut a latency spike short: cancelling the dominant work, shedding non-critical load, and time-boxing statements.",
              (
                  "## Pick the action that matches what scripts 01-06 showed\n"
                  "\n"
                  "A latency spike has exactly four realistic immediate responses. Choosing the\n"
                  "wrong one costs minutes you do not have, so match the evidence first.\n"
                  "\n"
                  + _cancel_vs_terminate_section() +
                  "\n"
                  "## Action A -- blocking dominates (script 04 returned rows)\n"
                  "\n"
                  "Do not tune anything. Go to `../lock-storm/README.md`, find the root blocker,\n"
                  "and clear it. Latency across every affected service normally returns within\n"
                  "seconds of the wait graph draining.\n"
                  "\n"
                  "## Action B -- one statement dominates (script 03 or 06)\n"
                  "\n"
                  "Confirm the owning service from `application_name`, then cancel the worst\n"
                  "offender -- one pid at a time:\n"
                  "\n"
                  "```sql\n"
                  "SELECT pg_cancel_backend(<pid from script 03>);\n"
                  "```\n"
                  "\n"
                  "If the same statement shape immediately reappears from many sessions, cancelling\n"
                  "individual backends is pointless: the application is generating it in a loop.\n"
                  "Ask the owning team to disable that code path or feature flag, which is the only\n"
                  "action that actually stops it.\n"
                  "\n"
                  "## Action C -- shed non-critical load\n"
                  "\n"
                  "*Precondition: scripts 01 and 02 show high, broadly distributed activity with no\n"
                  "single dominant statement and no blocking.*\n"
                  "\n"
                  "Shed in this order, never the reverse: reporting and analytics, then backfills\n"
                  "and reconciliation jobs, then non-trading product features, and only then\n"
                  "anything on the order, wallet or settlement path. Pause the job at its own\n"
                  "scheduler where possible -- that is cleaner than cancelling its database\n"
                  "sessions, which most schedulers will simply retry.\n"
                  "\n"
                  "If an index build or bulk maintenance operation is running, pausing it is almost\n"
                  "always correct: it can rerun tonight, the trading day cannot.\n"
                  "\n"
                  "## Action D -- time-box new work so the spike cannot deepen\n"
                  "\n"
                  "*Precondition: latency is caused by a small number of statements that the\n"
                  "application keeps re-issuing, and the owning team needs time to ship a fix.*\n"
                  "\n"
                  "A role-level statement timeout makes those statements fail fast instead of\n"
                  "queueing, which frees connections and stabilizes everything else. This is a real\n"
                  "configuration change affecting live traffic, so it needs the owning team's\n"
                  "agreement first -- their service will start receiving errors by design:\n"
                  "\n"
                  "```sql\n"
                  "-- Applies to NEW sessions of that role only; existing sessions are unaffected.\n"
                  "ALTER ROLE <role_name> SET statement_timeout = '5s';\n"
                  "```\n"
                  "\n"
                  "Record it as an incident-scoped change with an explicit owner and a revert step:\n"
                  "\n"
                  "```sql\n"
                  "ALTER ROLE <role_name> RESET statement_timeout;\n"
                  "```\n"
                  "\n"
                  "Never apply a blanket statement timeout to every role mid-incident. Settlement\n"
                  "and reconciliation jobs legitimately run long, and killing them halfway creates a\n"
                  "financial-integrity problem that is far more expensive than the latency.\n"
                  "\n"
                  "## After the spike clears\n"
                  "\n"
                  "Capture the evidence while it still exists: the queryids from script 06, the\n"
                  "wait-event mix from script 02, and the exact minute the step change started.\n"
                  "pg_stat_activity keeps nothing once sessions end, and without that evidence the\n"
                  "follow-up investigation restarts from zero.\n"
              ),
              "Match the action to the evidence, take one action at a time, and re-run scripts 01-04 after each one. Acting on two hypotheses simultaneously makes it impossible to know which change helped.",
              safety=ELEVATED_RISK_SESSION,
              expected_impact="Cancelling a statement aborts that statement only; a role-level timeout change causes the affected service's long statements to fail fast by design.",
              required_privileges=INCIDENT_OPERATOR_PRIVS,
              prerequisites="Scripts 01-06 completed and a dominant cause identified; owning-team agreement for any configuration change.",
              execution_location=INCIDENT_TARGET_INSTANCE,
              expected_runtime="Seconds per statement.",
              related_scripts="03_longest_active_queries.sql, 04_blocking_snapshot.sql",
              table_purpose="Guarded actions: clear blocking, cancel the dominant statement, shed load, time-box work."),
]

# ---------------------------------------------------------------------------
# 3. high-cpu (incident checklist version)
# ---------------------------------------------------------------------------
WORKFLOWS.append(_wf(
    slug="high-cpu",
    title="High CPU -- First Response Checklist",
    summary=(
        "CloudWatch is alarming on CPUUtilization for the writer or a reader "
        "and somebody needs an answer in the next five minutes. This is the "
        "rapid triage version: establish whether the CPU is doing useful "
        "work, find the sessions responsible, and decide what to cut. The "
        "deep-dive analysis of why a query is expensive belongs in "
        "`performance/high-cpu`; do not start there while an alarm is firing."
    ),
    symptoms=[
        "CPUUtilization sustained above 80-90% on the writer or a specific reader.",
        "Trading, order-cancel and balance-read latency climbing in step with the CPU curve.",
        "Active session count rising without any corresponding rise in completed transactions.",
        "Performance Insights showing Average Active Sessions well above the instance's vCPU count with CPU as the dominant component.",
        "Readers at high CPU while the writer looks fine, or the exact reverse -- the asymmetry is itself a strong clue.",
    ],
    business_impact=[
        "A CPU-saturated writer queues every order, cancel and wallet write behind runnable work, so the exchange's entire critical path slows at once.",
        "Sustained saturation eventually makes the instance unresponsive to new connections, converting a performance incident into an availability incident.",
        "Risk and compliance checks that gate withdrawals begin to time out, which either blocks customer withdrawals or, far worse, causes them to be skipped if the application fails open.",
    ],
    root_causes=[
        "A small number of expensive queries (a bad plan, a missing index, an unbounded scan) consuming most of the runnable time.",
        "A retry storm: an upstream service timing out and re-issuing the same query many times over, multiplying the load that caused the original timeout.",
        "Legitimate traffic growth or a market-volatility burst exceeding the current instance class.",
        "Connection churn: thousands of short-lived connections forcing constant backend startup, parsing and planning overhead.",
        "Maintenance work colliding with peak traffic: aggressive autovacuum, an index build, or a bulk backfill.",
        "Expensive per-row work in the query path -- user-defined functions, JSONB processing, regex predicates, or heavy sorting.",
        "Parallel query fan-out: a handful of statements each spawning workers and collectively oversubscribing every core.",
    ],
    investigation_strategy=[
        "Snapshot overall session load first, so you know whether this is many small units of work or a few large ones.",
        "Check the wait-event mix straight away -- CPU-bound work shows as active sessions with no wait event, and anything else means the CPU number is a symptom of a different problem.",
        "List the longest-running active queries and look for repetition of the same statement shape.",
        "Pull the top statements by total execution time from pg_stat_statements, which attributes cumulative cost far better than any instantaneous snapshot can.",
        "Check whether autovacuum or another maintenance operation is competing for the same cores.",
        "Act: cancel, shed, or scale -- and if the cause is a genuinely expensive query shape, hand it to the performance deep-dive rather than tuning it live.",
    ],
    prerequisites=[
        "`pg_monitor` role membership.",
        "`pg_stat_statements` for script 04 (the script degrades to a notice if it is absent).",
        "CloudWatch access to confirm which instances are actually hot -- there is no SQL query that returns CPU percentage, so this must come from outside the database.",
        "The instance class and its vCPU count, so you can judge whether the active session count is plausibly saturating it.",
    ],
    interpretation_guide=[
        "Active sessions with NULL wait events are the true CPU signal. If the active count is around or above the vCPU count and those sessions are not waiting on anything, the instance is genuinely CPU-bound.",
        "Active sessions that are mostly waiting on Lock or IO mean the CPU number is collateral damage; fixing CPU will not fix the incident.",
        "A few statements accounting for the bulk of total_exec_time in pg_stat_statements is the most actionable finding available -- it names the fix.",
        "A very high calls count with a small mean_exec_time is a volume problem, not a query problem, and is very often a retry storm rather than genuine user demand.",
        "Autovacuum workers running on large hot tables during peak hours can account for a surprising share of CPU, and unlike application work they can usually be deferred safely for a short period.",
        "Readers hot while the writer is idle means read traffic is being routed at them faster than they can serve it; add capacity or rebalance rather than investigating the writer.",
    ],
    remediation_immediate=[
        "Cancel the specific dominant backends after confirming ownership, per the runbook in this workflow -- cancel, never terminate, unless cancel has demonstrably failed.",
        "Ask the owning service to disable the offending code path or feature flag if the same statement immediately reappears from new sessions; cancelling backends cannot outrun an application loop.",
        "Route eligible read traffic to the reader endpoint if the writer is the hot instance and the reads are genuinely tolerant of replica lag.",
        "Defer competing maintenance work (index builds, backfills, manual vacuum) until the CPU curve is back under control.",
    ],
    remediation_short_term=[
        "Fix the plan for the top offenders identified in script 04, following the performance and query-optimization workflows.",
        "Put a transaction-mode pooler in front of the highest-churn services to remove connection-setup and planning overhead.",
        "Tune autovacuum on the hottest tables so it runs more often and more cheaply rather than rarely and expensively during peak hours.",
    ],
    remediation_long_term=[
        "Establish a documented scaling runbook tied to sustained Average Active Sessions rather than to raw CPU percentage, which is a lagging and misleading signal on its own.",
        "Move analytical and reporting consumers permanently off the writer.",
        "Add per-service query budgets and circuit breakers upstream, so a retry storm cannot convert a small slowdown into full CPU saturation.",
    ],
    production_safety=[
        "Scripts 01-05 are read-only and safe to run while the instance is saturated; they are catalog reads and add negligible load.",
        "Script 06 is a guarded manual runbook -- read it before executing anything in it.",
        "Do not restart the instance to 'reset' CPU. You lose the buffer cache, every in-flight order write fails, and the workload that caused the saturation returns within seconds against a cold cache.",
    ],
    escalation_criteria=[
        "CPU remains above 90% for more than 15 minutes despite mitigation, with customer-visible impact.",
        "The cause is a retry storm from an upstream service -- escalate to that team immediately; this cannot be fixed from inside the database.",
        "The workload is legitimate and the instance class is simply undersized -- a scaling decision is required beyond on-call authority.",
        "Both the writer and every reader are saturated simultaneously, which points at a cluster-wide or storage-layer problem worth an AWS support case.",
    ],
    related_issues=[
        "../production-triage/README.md",
        "../sudden-latency-spike/README.md",
        "../runaway-query/README.md",
        "../../performance/high-cpu/README.md",
        "../../database-health/comprehensive-health-check/README.md",
    ],
    aurora_notes=[
        "There is no SQL query that returns CPU utilization: CPUUtilization is an instance-level CloudWatch metric. The closest SQL-visible proxies are the count of active sessions with no wait event and cumulative execution time from pg_stat_statements.",
        "Aurora does not run the vacuum and checkpoint workload exactly as community PostgreSQL does, but autovacuum workers are still ordinary backends consuming instance CPU, and they are visible in pg_stat_activity like any other session.",
        "Performance Insights' Average Active Sessions compared against the instance's vCPU count is the fastest way to judge saturation: AAS consistently above vCPU count means work is queueing for CPU, regardless of what the raw CPU percentage looks like.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_session_load_snapshot",
               "Sizes the load in one query: how many sessions exist, in which states, and how long the longest have been running.",
               sb.activity_overview(),
               "Compare the active count against the instance's vCPU count. Active sessions at or above vCPU count means work is queueing for CPU. A large idle or idle-in-transaction population instead means the CPU is being consumed by something other than the connection count.",
               related_scripts="02_cpu_versus_wait_breakdown.sql",
               table_purpose="Session counts by state, with the longest query and transaction runtimes."),
    sql_script("02", "02_cpu_versus_wait_breakdown",
               "Separates genuine CPU-bound work from sessions that are merely waiting -- the check that decides whether this is really a CPU incident.",
               _combine(sb.wait_events_summary(), sb.connection_contention_by_wait_event()),
               "Active sessions with no wait event are the real CPU consumers. If most sessions are waiting on Lock or IO, the CPU alarm is a side effect and you should be in the lock-storm or latency workflow instead -- confirm this before doing anything else, because it inverts the entire response.",
               related_scripts="03_top_active_queries_now.sql",
               table_purpose="Wait-event mix, distinguishing runnable work from waiting work."),
    sql_script("03", "03_top_active_queries_now",
               "Lists the active queries running longest right now, so the dominant statement shape can be identified in seconds.",
               sb.active_long_running_queries(),
               "Look for repetition. The same normalized statement appearing across many pids is either a legitimate hot path that has become too expensive or a retry storm; a single long unique query alongside normal traffic is a runaway query. Note the pids for the runbook and the queryid for the deep dive.",
               related_scripts="04_top_statements_by_total_time.sql, ../runaway-query/README.md",
               table_purpose="Currently active queries above the runtime threshold."),
    sql_script("04", "04_top_statements_by_total_time",
               "Attributes cumulative execution time to specific statements, which an instantaneous snapshot cannot do.",
               _pgss_guarded(sb.pgss_top_by_total_time()),
               "Rank by total_exec_time, not mean: a 3ms statement called two million times costs far more CPU than a 5-second report run twice. A low cache_hit_pct on a top consumer means it is also driving IO, so fixing it pays twice.",
               required_privileges=PG_MONITOR_PLUS_PGSS,
               prerequisites="pg_stat_statements installed in the current database; the script prints a notice and exits cleanly if it is not.",
               related_scripts="../../performance/high-cpu/README.md",
               table_purpose="Top statements by cumulative execution time."),
    sql_script("05", "05_maintenance_competing_for_cpu",
               "Checks whether autovacuum or other maintenance work is competing with application traffic for the same cores.",
               _combine(sb.autovacuum_workers_active(), sb.dead_tuples_ranked()),
               "Several autovacuum workers on large hot tables during peak hours is a real and deferrable CPU cost. But check the dead-tuple ranking before deferring anything: a table with a very high dead_tuple_pct needs that vacuum, and starving it trades a CPU spike today for a bloat and wraparound problem next week.",
               related_scripts="06_cpu_mitigation_actions.md",
               table_purpose="Running vacuum workers plus the tables with the most dead tuples."),
    md_script("06", "06_cpu_mitigation_actions",
              "Guarded runbook for cutting CPU load fast: cancelling the dominant sessions, stopping a retry storm, deferring maintenance, and deciding to scale.",
              (
                  "## Order of operations\n"
                  "\n"
                  "Do the cheapest reversible thing first. Cancelling a query is reversible (it can\n"
                  "be rerun); scaling an instance is not free; restarting is never the answer.\n"
                  "\n"
                  + _cancel_vs_terminate_section() +
                  "\n"
                  "## Action A -- cancel the dominant sessions\n"
                  "\n"
                  "*Precondition: script 03 shows a small number of sessions with runtimes far above\n"
                  "everything else, and script 02 confirmed they are not merely waiting.*\n"
                  "\n"
                  "```sql\n"
                  "SELECT pg_cancel_backend(<pid from script 03>);\n"
                  "```\n"
                  "\n"
                  "Re-run script 03 after each cancel. If CPU does not move, the statement you\n"
                  "cancelled was not the cause -- stop cancelling and go back to the evidence.\n"
                  "\n"
                  "## Action B -- stop a retry storm\n"
                  "\n"
                  "*Precondition: the same statement shape immediately reappears from new pids after\n"
                  "each cancel, and script 04 shows a very high calls count with a small mean.*\n"
                  "\n"
                  "You cannot win this from the database side: the application is generating work\n"
                  "faster than you can cancel it. Escalate to the owning service and ask for one of:\n"
                  "\n"
                  "* the feature flag or code path disabled,\n"
                  "* the retry policy switched to exponential backoff with jitter and a cap,\n"
                  "* the service scaled down temporarily to reduce its request rate.\n"
                  "\n"
                  "As a database-side holding measure only, and only with that team's agreement, a\n"
                  "role-level timeout makes the storm fail fast instead of accumulating:\n"
                  "\n"
                  "```sql\n"
                  "ALTER ROLE <role_name> SET statement_timeout = '2s';   -- new sessions only\n"
                  "ALTER ROLE <role_name> RESET statement_timeout;        -- revert step\n"
                  "```\n"
                  "\n"
                  "## Action C -- defer competing maintenance\n"
                  "\n"
                  "*Precondition: script 05 shows vacuum workers or an index build on large tables\n"
                  "during peak traffic.*\n"
                  "\n"
                  "Cancelling an autovacuum worker is safe in the narrow sense -- autovacuum simply\n"
                  "reschedules the table -- but it is the wrong reflex if the table's dead-tuple\n"
                  "percentage is already high, and it is actively dangerous if the vacuum is running\n"
                  "to prevent transaction-ID wraparound (check `../../transactions-and-xid/`\n"
                  "before touching an anti-wraparound vacuum; those must be allowed to finish).\n"
                  "\n"
                  "```sql\n"
                  "SELECT pg_cancel_backend(<autovacuum worker pid from script 05>);\n"
                  "```\n"
                  "\n"
                  "A user-initiated index build or backfill is the better target: pause it at its\n"
                  "own scheduler so it does not immediately restart.\n"
                  "\n"
                  "## Action D -- scale\n"
                  "\n"
                  "*Precondition: the workload is legitimate, no single statement dominates, and the\n"
                  "instance is simply too small for current demand.*\n"
                  "\n"
                  "Adding a reader and shifting read traffic is the lower-risk move and needs no\n"
                  "failover. Resizing the writer's instance class requires a failover, so it costs a\n"
                  "write-unavailability window and a cold cache -- it needs the approval named in\n"
                  "your escalation policy and is rarely the right action while an incident is live.\n"
                  "\n"
                  "## What not to do\n"
                  "\n"
                  "* Do not terminate backends in bulk. Every client reconnects at once, and\n"
                  "  connection setup is itself CPU work -- the curve gets worse before it gets\n"
                  "  better.\n"
                  "* Do not run `ANALYZE` across the whole database as a blind fix. It adds load now\n"
                  "  and rarely addresses the statement actually burning the CPU.\n"
                  "* Do not reboot. You will lose the buffer cache and the in-flight order writes,\n"
                  "  and the workload returns within seconds against a cold instance.\n"
              ),
              "Take one action, re-measure, then decide the next. Each action names the script output that must be true first; without that evidence the action is a guess, and guesses during CPU saturation usually cost more CPU.",
              safety=ELEVATED_RISK_SESSION,
              expected_impact="Cancelling aborts the target statement only. A role-level timeout makes that role's long statements fail fast by design. Scaling a writer requires a failover window.",
              required_privileges=INCIDENT_OPERATOR_PRIVS,
              prerequisites="Scripts 01-05 completed, with script 02 confirming the load is genuinely CPU-bound rather than lock or IO wait.",
              execution_location=INCIDENT_TARGET_INSTANCE,
              expected_runtime="Seconds per statement.",
              related_scripts="03_top_active_queries_now.sql, 05_maintenance_competing_for_cpu.sql",
              table_purpose="Guarded actions: cancel dominant sessions, stop a retry storm, defer maintenance, scale."),
]

# ---------------------------------------------------------------------------
# 4. connection-exhaustion (incident checklist version)
# ---------------------------------------------------------------------------
WORKFLOWS.append(_wf(
    slug="connection-exhaustion",
    title="Connection Exhaustion -- First Response Checklist",
    summary=(
        "New connections are being refused with `FATAL: sorry, too many "
        "clients already` while existing sessions continue to work. This is "
        "the rapid triage version: find out who is holding the slots, "
        "reclaim enough of them to restore service, and identify the owning "
        "service so the slots do not simply refill. The structural work of "
        "pool sizing and connection budgeting belongs in "
        "`connections/connection-exhaustion`."
    ),
    symptoms=[
        "`FATAL: sorry, too many clients already` in application logs, or `remaining connection slots are reserved for roles with the SUPERUSER attribute`.",
        "New pods or services failing their startup health checks while already-running instances stay healthy.",
        "DatabaseConnections in CloudWatch flat-lining at a ceiling rather than fluctuating with traffic.",
        "Operators unable to open a psql session to investigate, because the slots are gone.",
        "A service that was just deployed or restarted unable to connect, while the fleet it replaced was fine.",
    ],
    business_impact=[
        "Any service that needs a NEW connection fails completely: newly started pods, scheduled settlement jobs, and reconciliation runs -- even though the database is healthy and fast for everyone already connected.",
        "Withdrawal and deposit processors that connect on demand rather than holding a pool are typically the first to fail, which directly affects customer funds movement.",
        "Responders lose their own access, which is why a reserved break-glass path matters more here than in any other incident type.",
    ],
    root_causes=[
        "A service deployed with a pool size that, multiplied by its replica count, exceeds the cluster's entire connection budget.",
        "A connection leak: sessions opened and never returned to the pool, visible as a steadily climbing idle count that never falls.",
        "Idle-in-transaction sessions holding slots (and snapshots, and locks) because the application failed to commit or roll back after an exception.",
        "A pooler misconfigured into session mode where transaction mode was intended, so multiplexing never happens.",
        "A deployment rollout that doubles connections briefly while old and new replicas overlap.",
        "A slowdown elsewhere in the database: each request holds its connection longer, so the same request rate needs far more concurrent connections.",
        "Batch or analytics tooling opening one connection per worker thread against the writer.",
    ],
    investigation_strategy=[
        "Confirm the ceiling and how close to it you are -- this takes one query and turns a vague report into a measured fact.",
        "Break the connections down by state, because idle, idle-in-transaction and active slots each have a different owner and a different fix.",
        "Attribute the slots to a service via application_name and user, so you know who to call while you are still reclaiming.",
        "List the long-idle sessions, which are the cheapest and safest slots to reclaim.",
        "List the idle-in-transaction sessions separately, which are more valuable to reclaim but carry rollback consequences.",
        "Reclaim carefully and in parallel with the owning service reducing its pool, then verify headroom has genuinely recovered.",
    ],
    prerequisites=[
        "`pg_monitor` role membership, plus `pg_signal_backend` (or `rds_superuser`) for any reclaim action.",
        "A break-glass connection path that is not subject to the same exhaustion -- superuser_reserved_connections exists precisely for this and should be verified before you need it.",
        "A contact path to each service that appears in application_name, because reclaiming slots without reducing demand is a temporary fix at best.",
    ],
    interpretation_guide=[
        "pct_utilized above roughly 95% is the actionable threshold: superuser_reserved_connections means the last few slots are already unavailable to application roles.",
        "A dominant 'idle' population means a pool is holding far more connections than it uses -- the cheapest possible reclaim, and a pool-sizing conversation.",
        "A dominant 'idle in transaction' population means an application bug: those sessions also hold snapshots and possibly locks, so they are hurting vacuum and concurrency as well as connection availability.",
        "A dominant 'active' population means the database is slow rather than leaked-into: each request holds its slot longer, so fix the slowness and the connection count falls by itself.",
        "One application_name holding a disproportionate share names the owning team immediately, which is usually the fastest path to a durable fix.",
        "Connection ages clustered within the last few minutes point at a deployment or a restart storm; ages spanning days point at a leak.",
    ],
    remediation_immediate=[
        "Reclaim long-idle sessions one pid at a time per the runbook, starting with the largest offender by application_name.",
        "Ask the owning service to reduce its pool size or scale in replicas in the same minute -- without that, reclaimed slots refill within seconds.",
        "Terminate idle-in-transaction sessions that are also blocking others, after confirming the rollback is safe for that transaction.",
        "If the underlying cause is database slowness rather than leakage, stop reclaiming and switch to the latency or lock-storm workflow instead.",
    ],
    remediation_short_term=[
        "Apply a per-role connection limit so no single service can consume the whole budget again: this is a documented, revertible configuration change, not an emergency action.",
        "Set `idle_in_transaction_session_timeout` for application roles so PostgreSQL reclaims leaked transaction slots automatically.",
        "Move the highest-churn services behind a transaction-mode pooler.",
    ],
    remediation_long_term=[
        "Publish a connection budget per service that sums to comfortably less than max_connections, and enforce it in deployment manifests rather than in a wiki page.",
        "Alert on connection utilization at 70% and 85%, so exhaustion is a scheduled conversation rather than a page.",
        "Standardize pool configuration across services so the per-replica connection count is a reviewed value rather than a framework default copied between repositories.",
    ],
    production_safety=[
        "Scripts 01-05 are read-only and safe to run during exhaustion, provided you can still get a connection at all -- this is exactly what the reserved superuser slots are for.",
        "Script 06 ends other sessions and changes role-level limits; read it fully before executing anything.",
        "Never terminate every matching session in a single set-returning statement. Simultaneous mass reconnection is its own outage, and it is entirely avoidable.",
    ],
    escalation_criteria=[
        "You cannot obtain a connection at all, even through the reserved break-glass path -- escalate to AWS support immediately.",
        "Slots refill to the ceiling within seconds of every reclaim and the owning service cannot or will not reduce its pool -- escalate to that service's leadership; this is now an organizational decision, not a database one.",
        "The exhaustion is a symptom of database slowness rather than leakage, and the slowness is unresolved -- escalate on the latency track instead.",
        "Withdrawal or settlement processors have been unable to connect for more than a few minutes -- escalate to treasury and compliance in parallel.",
    ],
    related_issues=[
        "../production-triage/README.md",
        "../database-unavailable/README.md",
        "../application-timeouts/README.md",
        "../../connections/connection-exhaustion/README.md",
        "../../concurrency-and-locking/blocked-queries/README.md",
    ],
    aurora_notes=[
        "Aurora derives max_connections from the instance class's memory through the parameter-group formula, so raising it is a parameter-group change (and usually a restart), not a live mitigation -- plan the budget around the instance class instead.",
        "RDS Proxy holds its own pool of database connections and multiplexes application connections onto them; when a proxy is in the path, the connection count the database sees is the proxy's, and the real leak may be between the application and the proxy rather than between the proxy and the database.",
        "Aurora reader instances have their own independent connection ceilings, so read traffic that is correctly routed to readers does not consume writer slots -- and misrouted read traffic is a common, easily fixed cause of writer exhaustion.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_connection_headroom",
               "Measures how close the instance is to its connection ceiling, including the reserved superuser slots.",
               sb.max_connections_headroom(),
               "pct_utilized at or above roughly 95% confirms exhaustion: with superuser_reserved_connections subtracted, application roles are already being refused. Record this number before and after every reclaim action so you can prove whether it is working.",
               related_scripts="02_connections_by_state.sql",
               table_purpose="Current connection count against max_connections and reserved slots."),
    sql_script("02", "02_connections_by_state",
               "Breaks the connections down by state, which determines both who owns them and how safely they can be reclaimed.",
               sb.connections_by_state(),
               "Idle means a pool is hoarding slots (cheap to reclaim). Idle in transaction means an application bug holding snapshots and locks (valuable to reclaim, but with rollback consequences). Active means the database is slow and each request is holding its slot longer -- in that case stop reclaiming and fix the slowness.",
               related_scripts="03_connections_by_application.sql",
               table_purpose="Connection counts by database and state, with percent of max_connections."),
    sql_script("03", "03_connections_by_application",
               "Attributes the connections to a service and user so the owning team can be contacted while reclaim is still in progress.",
               sb.connections_by_application_and_user(),
               "One application_name holding a disproportionate share names the owning team immediately. A large '(unset)' group means those services do not set application_name, which is a follow-up action worth insisting on -- attribution is what makes this incident solvable in minutes rather than hours.",
               related_scripts="04_long_idle_sessions.sql",
               table_purpose="Connection counts by application_name, user and state."),
    sql_script("04", "04_long_idle_sessions",
               "Lists plain idle sessions ranked by idle duration -- the cheapest and safest slots to reclaim.",
               _idle_sessions_by_age(),
               "An idle session holds no locks, no snapshot and no in-flight work, so reclaiming it costs a healthy client one reconnect. Connection_age spanning days alongside a long idle_duration is a leak; ages clustered in the last few minutes are a deployment or restart storm instead.",
               related_scripts="05_idle_in_transaction_sessions.sql",
               table_purpose="Plain idle sessions ranked by how long they have been idle."),
    sql_script("05", "05_idle_in_transaction_sessions",
               "Lists sessions holding an open transaction while idle -- slots that are also damaging vacuum and concurrency.",
               _combine(sb.idle_in_transaction_sessions(), sb.blocking_sessions_detail()),
               "These are the highest-value reclaims because they free a slot AND release a snapshot and any locks. An idle-in-transaction session that also appears as a blocking pid in the second result set is the single best target in this workflow -- it is causing active harm while doing no work at all.",
               related_scripts="06_reclaim_connection_slots.md, ../../concurrency-and-locking/blocked-queries/README.md",
               table_purpose="Idle-in-transaction sessions, plus any of them that are blocking others."),
    md_script("06", "06_reclaim_connection_slots",
              "Guarded runbook for reclaiming connection slots safely and for applying a per-role connection limit so they do not immediately refill.",
              (
                  "## Reclaim in order of increasing risk\n"
                  "\n"
                  "1. Plain `idle` sessions, oldest first (script 04).\n"
                  "2. `idle in transaction` sessions that are also blocking others (script 05).\n"
                  "3. `idle in transaction` sessions that are not blocking anyone.\n"
                  "4. Nothing else. Active sessions are doing work for customers; if they are the\n"
                  "   problem, the answer is the latency workflow, not a termination.\n"
                  "\n"
                  + _cancel_vs_terminate_section() +
                  "\n"
                  "## Action A -- reclaim idle slots\n"
                  "\n"
                  "Re-list the candidates immediately before acting -- a list from two minutes ago\n"
                  "is already stale, and pids get reused:\n"
                  "\n"
                  "```sql\n"
                  "SELECT pid, usename, application_name, client_addr,\n"
                  "       now() - state_change AS idle_duration\n"
                  "FROM pg_stat_activity\n"
                  "WHERE state = 'idle'\n"
                  "  AND backend_type = 'client backend'\n"
                  "  AND pid <> pg_backend_pid()\n"
                  "  AND application_name = '<application_name from script 03>'\n"
                  "ORDER BY idle_duration DESC;\n"
                  "```\n"
                  "\n"
                  "Then, one pid at a time:\n"
                  "\n"
                  "```sql\n"
                  "SELECT pg_terminate_backend(<pid>);\n"
                  "```\n"
                  "\n"
                  "Re-run script 01 after every few reclaims. If pct_utilized does not fall, the\n"
                  "slots are refilling as fast as you free them and the fix is Action C, not more\n"
                  "terminations.\n"
                  "\n"
                  "**Do not** write a statement that terminates all matching sessions at once. Mass\n"
                  "simultaneous reconnection is a second incident, and connection setup is itself\n"
                  "expensive -- you will spike CPU on an instance that is already in trouble.\n"
                  "\n"
                  "## Action B -- reclaim idle-in-transaction slots\n"
                  "\n"
                  "*Precondition: script 05 listed them, and you have checked whether each one is\n"
                  "blocking other sessions.*\n"
                  "\n"
                  "Terminating these rolls back whatever the transaction had already done. For a\n"
                  "session whose last statement touched a financial table, the financial-write\n"
                  "safety gate above applies in full -- get the owning team's confirmation first.\n"
                  "\n"
                  "```sql\n"
                  "SELECT pg_terminate_backend(<pid from script 05>);\n"
                  "```\n"
                  "\n"
                  "(A cancel does not help here: there is no statement running to cancel. The\n"
                  "session is idle *inside* a transaction, so only a terminate ends it.)\n"
                  "\n"
                  "## Action C -- stop the slots refilling\n"
                  "\n"
                  "Reclaiming without reducing demand is a treatment, not a cure. Do both:\n"
                  "\n"
                  "* Ask the owning service to reduce its pool size or scale in replicas now.\n"
                  "* Apply a per-role connection limit as an incident-scoped guardrail. This affects\n"
                  "  only NEW connections for that role; existing sessions are untouched. Agree it\n"
                  "  with the owning team first -- their service will start seeing connection\n"
                  "  errors by design, which is the point:\n"
                  "\n"
                  "```sql\n"
                  "-- Choose a limit that leaves the rest of the fleet room to breathe.\n"
                  "ALTER ROLE <role_name> CONNECTION LIMIT 50;\n"
                  "\n"
                  "-- Revert step, to be run once the service's own pool configuration is fixed:\n"
                  "ALTER ROLE <role_name> CONNECTION LIMIT -1;\n"
                  "```\n"
                  "\n"
                  "Never apply a connection limit to a role used by settlement, withdrawal or\n"
                  "reconciliation processing without explicit treasury-side agreement: blocking\n"
                  "those connections trades a connection incident for a funds-movement incident.\n"
                  "\n"
                  "## Verify\n"
                  "\n"
                  "Re-run `01_connection_headroom.sql`. You are done when pct_utilized is back\n"
                  "below roughly 80% and stays there across two consecutive checks a minute apart.\n"
                  "A number that falls and immediately climbs again means demand, not leakage, and\n"
                  "the durable fix lives in `../../connections/connection-exhaustion/README.md`.\n"
              ),
              "Reclaim in the documented order, one pid at a time, re-measuring headroom as you go. If headroom does not improve after a reclaim round, stop terminating and fix demand instead -- more terminations will not help.",
              safety=ELEVATED_RISK_SESSION,
              expected_impact="Terminating an idle session drops one pooled connection. Terminating an idle-in-transaction session additionally rolls back its open transaction. A role connection limit causes new connections above the limit to be refused by design.",
              required_privileges=INCIDENT_OPERATOR_PRIVS,
              prerequisites="Scripts 01-05 completed, the owning service identified from script 03, and agreement from that team before any role-level limit is applied.",
              execution_location=INCIDENT_TARGET_INSTANCE,
              expected_runtime="Seconds per statement.",
              related_scripts="01_connection_headroom.sql, 04_long_idle_sessions.sql, 05_idle_in_transaction_sessions.sql",
              table_purpose="Guarded actions: reclaim idle slots, reclaim idle-in-transaction slots, apply a role connection limit."),
]

# ---------------------------------------------------------------------------
# 5. lock-storm
# ---------------------------------------------------------------------------
WORKFLOWS.append(_wf(
    slug="lock-storm",
    title="Lock Storm",
    summary=(
        "A large number of sessions are simultaneously waiting on locks, so "
        "the database is up and has plenty of CPU but is effectively frozen "
        "for the affected tables. Order writes, balance updates and ledger "
        "inserts queue behind a wait graph that is usually rooted in one or "
        "two sessions. This workflow finds that root within minutes and "
        "clears it safely."
    ),
    symptoms=[
        "A sudden cliff in throughput with CPU falling rather than rising -- the instance is idle because everything is waiting.",
        "Many sessions with `wait_event_type = 'Lock'` in pg_stat_activity, all stacked on a small number of relations.",
        "Application timeouts concentrated on one table or one feature (order placement, balance update) while unrelated features work normally.",
        "A queue of sessions that grows monotonically and does not drain on its own.",
        "The incident started at a discrete moment, often correlated with a migration, a batch job, or a long-running transaction opening.",
    ],
    business_impact=[
        "Writes to the order book and ledger stop entirely for the affected tables, so customers cannot place, amend or cancel orders on those markets.",
        "Because the queue grows rather than drains, a lock storm reliably escalates into connection exhaustion within minutes -- one incident becomes two.",
        "Settlement and reconciliation jobs blocked mid-run leave partially applied batches that need manual verification even after the storm clears.",
    ],
    root_causes=[
        "One long-running or idle-in-transaction session holding a lock that a hot code path needs on every request.",
        "A DDL statement (ALTER TABLE, non-concurrent CREATE INDEX, TRUNCATE) taking or waiting for an AccessExclusiveLock on a hot table, so every subsequent query queues behind its lock request.",
        "Hot-row contention that crossed a tipping point: the same row (a market's summary row, a shared counter, an omnibus wallet balance) updated by more concurrent transactions than it can serialize.",
        "A batch job taking row locks across a wide range in a single transaction rather than in small committed chunks.",
        "An unindexed foreign key or filter column causing an UPDATE or DELETE to lock far more rows than the business logic intended.",
        "A deploy that changed lock-acquisition order between two code paths, converting occasional contention into a persistent pile-up.",
    ],
    investigation_strategy=[
        "Size the storm first: how many sessions are waiting, and on what wait-event types. This distinguishes a genuine lock storm from general slowness.",
        "List the blocked sessions and their blocking pids.",
        "Rank the blockers by blast radius and, critically, identify which of them are true roots -- blockers that are not themselves blocked.",
        "Inspect the lock detail so you know exactly which relation and lock mode is at the centre of the storm.",
        "Check specifically for DDL-strength locks and for very old transactions, which are the two most common roots.",
        "Clear the root: cancel first, terminate only if cancel fails and the safety gate is satisfied.",
    ],
    prerequisites=[
        "`pg_monitor` role membership, plus `pg_signal_backend` (or `rds_superuser`) to clear a blocker.",
        "A connection that is not itself blocked -- connect and confirm you can run a trivial query before starting.",
        "Knowledge of which tables are on the trading and funds-movement hot path, so you can judge the blast radius correctly.",
        "`log_lock_waits` enabled in the parameter group is strongly recommended, so the storm is also reconstructable from CloudWatch Logs afterwards.",
    ],
    interpretation_guide=[
        "The key column in the blast-radius ranking is blocker_is_itself_blocked_by_count. Zero means a true root: clearing it releases the chain. Non-zero means a middle link, and clearing it accomplishes nothing.",
        "A blocker whose state is `idle in transaction` is the safest and most satisfying target: it is doing no work at all while holding everyone up.",
        "A blocker that is `active` and legitimately executing needs owner coordination -- it may be a settlement run whose rollback is more expensive than the storm.",
        "A DDL statement with granted = false is a special and very common case: the DDL is itself waiting, and every query that arrived after it is queued behind its lock request. Cancelling the DDL is usually the cheapest possible fix and is entirely safe.",
        "Many waiters on the same relation with the same lock mode means the storm is structural (hot row or hot table), so expect it to recur until the data model or access pattern changes.",
        "If the blocked count is large but the blocker set is empty, the sessions are waiting on something other than a heavyweight lock -- re-read the wait-event types before acting.",
    ],
    remediation_immediate=[
        "Cancel the true root blocker. For a waiting DDL statement this is both the fastest and the safest action, because a cancelled DDL rolls back cleanly with no data change.",
        "If cancel does not clear it within about 15 seconds and the financial-write safety gate is satisfied, terminate the root blocker.",
        "If the root is a batch job, stop the job at its scheduler as well, or it will simply reopen the same transaction and restart the storm.",
        "After the chain drains, immediately re-check connection headroom: a lock storm usually leaves connection pressure behind it.",
    ],
    remediation_short_term=[
        "Set `lock_timeout` for the roles that run DDL and batch work, so a statement that cannot get its lock fails fast instead of blocking everything behind it.",
        "Set `idle_in_transaction_session_timeout` for application roles so an abandoned transaction cannot become a storm root.",
        "Convert the offending DDL to the concurrent, lock-light pattern documented in the schema-changes category before it is retried.",
        "Break wide-range batch updates into small committed chunks ordered by primary key.",
    ],
    remediation_long_term=[
        "Redesign the hot-row patterns behind repeat storms -- shard a global counter, or move to an append-only ledger with periodic aggregation instead of in-place updates on one row.",
        "Make a lock-risk review mandatory for every migration touching a hot table, with the expected lock mode and duration stated in the change request.",
        "Add monitoring on blocked-session count with alerting well below the level at which customers notice, so a storm is caught while it is still a chain of three.",
    ],
    production_safety=[
        "Scripts 01-05 are read-only and safe to run during the storm; they add negligible load, and pg_blocking_pids() is the correct, queue-order-aware way to read the wait graph.",
        "Script 06 ends sessions and must be read fully first.",
        "Never terminate blockers in bulk to 'clear the graph'. You will roll back legitimate transactions you have not identified, and on a ledger or wallet table that creates a reconciliation problem far worse than the storm.",
    ],
    escalation_criteria=[
        "The root blocker is a system or replication process rather than an application backend -- escalate to database engineering and do not signal it.",
        "The chain does not clear after the identified root is resolved, which means a second root exists and the graph needs re-reading rather than more terminations.",
        "The blocker is a settlement, withdrawal or reconciliation transaction whose rollback has financial consequences -- escalate to treasury and compliance before acting, even if that means the storm runs longer.",
        "Storms on the same relation recur more than once in a week -- escalate as a structural data-model issue rather than continuing to treat each occurrence as an incident.",
    ],
    related_issues=[
        "../production-triage/README.md",
        "../database-unavailable/README.md",
        "../application-timeouts/README.md",
        "../post-deployment-incident/README.md",
        "../../concurrency-and-locking/blocked-queries/README.md",
        "../../schema-changes/failed-index-build/README.md",
    ],
    aurora_notes=[
        "Lock waits are instance-local: a storm on the writer is invisible on the readers, so always confirm which instance you are connected to before concluding that a cluster is or is not affected.",
        "Aurora exports lock-wait log lines (when log_lock_waits is enabled) to CloudWatch Logs rather than to a local file, which makes CloudWatch Logs Insights the place to reconstruct the storm's timeline after the fact -- pg_locks retains nothing once the waits clear.",
        "Aurora Performance Insights attributes waiting time to the Lock wait-event class in its Average Active Sessions chart, which is usually the fastest way to establish the exact minute the storm started and whether it has genuinely ended.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_lock_wait_scale",
               "Sizes the storm: how many backends are waiting, on what, and for how long.",
               _combine(sb.connection_contention_by_wait_event(), sb.wait_events_summary()),
               "A large backend_count for wait_event_type = 'Lock' relative to total sessions confirms a lock storm rather than general slowness. If the dominant waits are IO or Client instead, you are in the wrong workflow -- go back to the latency or connection triage.",
               related_scripts="02_blocked_sessions.sql",
               table_purpose="Scale of lock waiting across the instance, by wait event and state."),
    sql_script("02", "02_blocked_sessions",
               "Lists every session currently blocked and the pids blocking it, using the queue-order-aware pg_blocking_pids() helper.",
               sb.blocked_sessions(),
               "The count of rows is your blast radius; the blocked_duration spread tells you how long this has been building. Note that many blocked sessions can share very few distinct blocking pids -- that ratio is the good news in this incident, because it means a single action can fix everything.",
               related_scripts="03_root_blockers_by_blast_radius.sql",
               table_purpose="Every blocked session with its blocking pids and wait duration."),
    sql_script("03", "03_root_blockers_by_blast_radius",
               "Collapses the wait graph to the handful of blockers that matter, and identifies which of them are true roots.",
               _root_blockers_by_blast_radius(),
               "Act only on rows where blocker_is_itself_blocked_by_count = 0: those are true roots. Among them, prefer the one with the largest directly_blocked_sessions, and prefer a blocker whose state is 'idle in transaction' -- it is holding everyone up while doing no work at all.",
               related_scripts="04_lock_detail_at_the_root.sql",
               table_purpose="Blockers ranked by how many sessions they block, flagging true roots."),
    sql_script("04", "04_lock_detail_at_the_root",
               "Shows the exact relations and lock modes at the centre of the storm.",
               sb.lock_detail_by_mode(),
               "Match relation_name against your known hot tables (orders, trades, wallets, ledger_entries) to describe the customer impact accurately in the incident channel. Repeated rows for one relation in one mode means the storm is structural and will recur until the access pattern changes.",
               related_scripts="05_ddl_and_old_transactions.sql",
               table_purpose="Raw lock detail by relation and mode, granted and waiting."),
    sql_script("05", "05_ddl_and_old_transactions",
               "Checks the two most common storm roots: a DDL statement queued on a strong lock, and a very old open transaction.",
               _combine(sb.ddl_lock_waits(), sb.long_running_transactions()),
               "A DDL row with granted = false means the DDL is itself waiting and everything that arrived after it is queued behind its request -- cancelling that DDL is usually the cheapest and safest fix available, because a cancelled DDL rolls back cleanly with no data change. A transaction older than the storm is the other classic root.",
               related_scripts="06_clear_the_root_blocker.md, ../../schema-changes/failed-index-build/README.md",
               table_purpose="DDL-strength lock waits plus the oldest open transactions."),
    md_script("06", "06_clear_the_root_blocker",
              "Guarded runbook for clearing the root of a lock storm: cancel first, terminate only when justified, and verify the graph actually drained.",
              (
                  "## One root at a time\n"
                  "\n"
                  "A lock storm is cleared by resolving the true root of the wait graph, not by\n"
                  "signalling everything that looks suspicious. Take the single root identified in\n"
                  "script 03 (`blocker_is_itself_blocked_by_count = 0`, largest\n"
                  "`directly_blocked_sessions`), act on it, then re-measure.\n"
                  "\n"
                  + _cancel_vs_terminate_section() +
                  "\n"
                  "## Step 1 -- re-confirm the root immediately before acting\n"
                  "\n"
                  "Wait graphs change second to second, and pids are reused. Re-run\n"
                  "`03_root_blockers_by_blast_radius.sql` and read the pid out loud to the second\n"
                  "engineer on the call before you type it.\n"
                  "\n"
                  "## Step 2 -- special case: the root is a waiting DDL statement\n"
                  "\n"
                  "*Precondition: script 05 shows a DDL statement with `granted = false`.*\n"
                  "\n"
                  "Cancel the DDL, not the transaction it is waiting on. A cancelled DDL statement\n"
                  "rolls back cleanly, has changed no data, and its cancellation instantly drains\n"
                  "every query that queued behind its lock request:\n"
                  "\n"
                  "```sql\n"
                  "SELECT pg_cancel_backend(<DDL pid from script 05>);\n"
                  "```\n"
                  "\n"
                  "Then tell whoever issued it not to retry until the migration is converted to the\n"
                  "concurrent, lock-light pattern and given a `lock_timeout` -- otherwise the next\n"
                  "attempt recreates this incident exactly.\n"
                  "\n"
                  "## Step 3 -- general case: cancel the root blocker\n"
                  "\n"
                  "```sql\n"
                  "SELECT pg_cancel_backend(<root blocker pid from script 03>);\n"
                  "```\n"
                  "\n"
                  "Wait about 15 seconds, then re-run `02_blocked_sessions.sql`. A draining graph\n"
                  "means you are done; move to verification.\n"
                  "\n"
                  "Note the one case where cancel cannot work: if the root's state is `idle in\n"
                  "transaction`, there is no running statement to cancel. The session is idle inside\n"
                  "an open transaction, so only a terminate will end it -- go straight to step 4,\n"
                  "applying the safety gate.\n"
                  "\n"
                  "## Step 4 -- terminate, only with the safety gate satisfied\n"
                  "\n"
                  "```sql\n"
                  "SELECT pg_terminate_backend(<root blocker pid from script 03>);\n"
                  "```\n"
                  "\n"
                  "This rolls back the blocker's entire transaction. If its statement text touches\n"
                  "`ledger_entries`, `wallets`, `withdrawals`, `deposits`, `trades` or `orders`, the\n"
                  "financial-write safety gate above applies in full and without exception. If the\n"
                  "owning team cannot confirm that a rollback is safe, the correct answer may be to\n"
                  "let the storm continue while they finish -- say so explicitly in the incident\n"
                  "channel so that decision is a shared, recorded one.\n"
                  "\n"
                  "## Step 5 -- verify, and do not stop early\n"
                  "\n"
                  "1. Re-run `02_blocked_sessions.sql`: the blocked count should fall sharply.\n"
                  "2. Re-run `03_root_blockers_by_blast_radius.sql`: if a NEW true root appears, the\n"
                  "   storm had more than one root. Repeat from step 1 rather than assuming failure.\n"
                  "3. Check connection headroom with `../connection-exhaustion/README.md` script 01.\n"
                  "   Storms leave behind a pile of connections that were waiting, and the recovery\n"
                  "   surge is a common second incident.\n"
                  "4. Confirm with the affected services that latency has actually recovered. A\n"
                  "   drained lock graph is necessary but not sufficient evidence.\n"
                  "\n"
                  "## Never do this\n"
                  "\n"
                  "Do not write a statement that signals every blocker at once. You will roll back\n"
                  "transactions nobody has identified, on tables nobody has checked, and on a ledger\n"
                  "or wallet table that turns a ten-minute lock storm into a multi-day reconciliation.\n"
              ),
              "Clear exactly one true root, verify, and repeat only if a new true root appears. The verification step is not optional: a storm with two roots looks identical to a failed remediation if you stop measuring.",
              safety=ELEVATED_RISK_SESSION,
              expected_impact="A cancel aborts the blocker's current statement. A terminate rolls back its entire transaction. Both release the locks the storm is queued on.",
              required_privileges=INCIDENT_OPERATOR_PRIVS,
              prerequisites="Scripts 01-05 completed, a true root identified, and the financial-write safety gate satisfied before any terminate.",
              execution_location=INCIDENT_TARGET_INSTANCE,
              expected_runtime="Seconds to act; a terminated long transaction may take minutes to roll back.",
              related_scripts="02_blocked_sessions.sql, 03_root_blockers_by_blast_radius.sql, 05_ddl_and_old_transactions.sql",
              table_purpose="Guarded actions: cancel a waiting DDL, cancel or terminate the root blocker, verify the graph drained."),
]

# ---------------------------------------------------------------------------
# 6. runaway-query
# ---------------------------------------------------------------------------
WORKFLOWS.append(_wf(
    slug="runaway-query",
    title="Runaway Query",
    summary=(
        "A single query is consuming a disproportionate share of the "
        "instance's resources -- running for minutes on an OLTP path, "
        "spilling gigabytes of temp files, holding locks that other sessions "
        "need, or all three. This workflow identifies it precisely, "
        "quantifies what it is actually costing, and stops it with the "
        "smallest possible intervention."
    ),
    symptoms=[
        "One session in pg_stat_activity with a query_runtime orders of magnitude above everything else.",
        "A temp-file volume spike with no corresponding growth in legitimate workload.",
        "Other sessions blocked behind the one long-running statement.",
        "A reporting, export or reconciliation query accidentally pointed at the writer instead of a reader.",
        "An unbounded query -- a missing WHERE clause, a missing join predicate, or a parameter that arrived as NULL and matched everything.",
    ],
    business_impact=[
        "A runaway query on the writer competes directly with order and ledger writes for CPU, memory and IO, so one careless analytical statement can degrade the entire trading platform.",
        "If it holds locks, it converts into a lock storm and stops the affected tables completely.",
        "Long-running queries hold back the vacuum horizon for as long as they run, so a query left alone for hours also leaves behind bloat and a delayed freeze horizon.",
    ],
    root_causes=[
        "A missing or non-selective predicate, so the query scans the whole table (or the whole partition set) instead of a narrow range.",
        "A plan regression: the statement was fine yesterday, and stale statistics or a data-distribution change flipped it to a nested loop over a large set.",
        "An analytical or export query run against the writer instead of a reader endpoint, often by a human in a console.",
        "A parameter binding bug, most commonly a NULL or an empty filter list that widens the result set to everything.",
        "A cartesian product from a forgotten join condition in a hand-written operational query.",
        "A one-off data-fix or backfill statement run without batching during trading hours.",
    ],
    investigation_strategy=[
        "Find the candidates: active queries running far longer than the workload's normal profile.",
        "Pull full forensic detail on the specific backend, including the complete query text, its transaction age, and how many other sessions it is blocking.",
        "Quantify the collateral damage: is it blocking anything, and is it spilling temp files or driving IO?",
        "Check the statement's history to distinguish a normally-fine statement that regressed from a statement that has always been expensive.",
        "Stop it with the smallest intervention that works -- cancel first, terminate only if cancel fails and the safety gate is satisfied.",
    ],
    prerequisites=[
        "`pg_monitor` role membership, plus `pg_signal_backend` (or `rds_superuser`) to stop the query.",
        "A way to identify the query's owner: application_name, usename, or client_addr. Without an owner, you cannot judge whether stopping it is safe.",
        "`pg_stat_statements` for the history check (optional -- the script prints a notice if absent).",
    ],
    interpretation_guide=[
        "The full query text from script 02 is the single most important artifact in this workflow. Capture it before you act: once the backend is gone, pg_stat_activity retains nothing.",
        "sessions_this_backend_blocks greater than zero changes the urgency completely -- the runaway is now also a blocker, and the incident is a lock storm in the making.",
        "A txn_runtime much larger than the query_runtime means this statement is part of a longer transaction, so cancelling the statement leaves the transaction (and its locks and snapshot) open. In that case cancel, then require the client to end its transaction, or terminate.",
        "Large temp_blks_written against the statement's history means it is spilling sorts or hashes to disk, which is both a symptom of an undersized work_mem and a large driver of IO.",
        "A statement with a high historical mean that has always been slow is a candidate to move to a reader, not necessarily to kill on sight.",
        "backend_type that is not `client backend` means this is not an application query at all -- never signal it; escalate instead.",
    ],
    remediation_immediate=[
        "Cancel the specific backend after capturing the query text and confirming ownership.",
        "If the statement is part of an open transaction, follow the cancel by confirming with the owner that their client ends the transaction -- otherwise the locks and snapshot survive the cancel.",
        "If cancel has demonstrably failed and the safety gate is satisfied, terminate.",
        "Tell the owner before they retry: an unmodified retry reproduces this incident within minutes.",
    ],
    remediation_short_term=[
        "Set `statement_timeout` for the role that ran it, so the same class of query fails fast next time instead of running for an hour.",
        "Point reporting, export and ad-hoc analytical work at the reader endpoint, and make that the default in the tooling rather than a convention.",
        "Add the missing index or predicate the query needed, following the concurrent index build pattern.",
    ],
    remediation_long_term=[
        "Give analysts and operators a dedicated read-only role on the reader endpoint with a conservative statement_timeout baked into the role, so the safe path is also the easy path.",
        "Require batching for all data-fix and backfill statements, with an explicit chunk size and commit interval.",
        "Alert on any single query exceeding a duration threshold on the writer, so runaways are caught by monitoring rather than by customers.",
    ],
    production_safety=[
        "Scripts 01-04 are read-only. Script 02 is explicitly safe to run unedited: its :target_pid defaults to 0, which matches no backend, so an unedited run simply returns no rows.",
        "Script 05 ends a session and must be read fully before use.",
        "Capture the full query text before stopping anything. Acting first and investigating afterwards destroys the only evidence that explains the incident.",
    ],
    escalation_criteria=[
        "The runaway is a settlement, reconciliation or withdrawal-processing statement -- escalate to treasury and compliance before stopping it, because a partially applied financial batch is worse than a slow one.",
        "The backend is not a client backend -- escalate to database engineering and do not signal it.",
        "Cancel and terminate both fail to stop it, which points at a stuck backend and warrants an AWS support case.",
        "The same runaway shape recurs after remediation, which means the fix is upstream in the application or in analyst tooling rather than in this incident.",
    ],
    related_issues=[
        "../production-triage/README.md",
        "../high-cpu/README.md",
        "../sudden-latency-spike/README.md",
        "../lock-storm/README.md",
        "../../performance/high-cpu/README.md",
    ],
    aurora_notes=[
        "A runaway query on an Aurora reader consumes that reader's CPU and memory but cannot block writer traffic on locks, because readers serve read-only snapshots -- which is exactly why routing analytical work to readers is the durable fix rather than a workaround.",
        "Temp files on Aurora are written to the instance's local storage, which is finite and separate from the cluster volume; a query spilling aggressively can exhaust local storage and fail with a disk-full error that has nothing to do with your cluster's actual data size.",
        "Aurora Performance Insights retains the statement text for top consumers even after the session ends, which is often the only remaining evidence once a runaway has been terminated -- check there if the query text was not captured in time.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_runaway_candidates",
               "Lists the active queries running far longer than the workload's normal profile, to identify the candidate.",
               sb.active_long_running_queries(),
               "On a crypto-exchange OLTP path, anything beyond a few seconds is already abnormal. Pick the single worst row by query_runtime, note its pid, and check its application_name and usename -- a query from a human's console session is a very different decision from one on the order path.",
               related_scripts="02_target_backend_detail.sql",
               table_purpose="Active queries above the runtime threshold, ranked by runtime."),
    sql_script("02", "02_target_backend_detail",
               "Captures complete forensic detail for the specific backend, including its full query text and how many sessions it is blocking.",
               _target_backend_detail(),
               "Set :target_pid to the pid from script 01 first; unedited, this script matches nothing and returns zero rows by design. Copy full_query_text into the incident channel before doing anything else -- it disappears the moment the backend ends. sessions_this_backend_blocks above zero means this is also a blocking incident.",
               related_scripts="01_runaway_candidates.sql, 03_collateral_damage.sql",
               table_purpose="Full detail for one backend: query text, ages, wait state, blocking relationships."),
    sql_script("03", "03_collateral_damage",
               "Quantifies what the runaway is costing everyone else: sessions blocked behind it and temp-file pressure across the database.",
               _combine(sb.blocked_sessions(), sb.temp_file_usage_by_database()),
               "Blocked sessions behind the runaway raise the urgency and change the follow-up: after stopping it, verify through the lock-storm workflow that the graph actually drained. A large temp_bytes value alongside a long-running sort or hash confirms the query is spilling to local storage, which is a real risk to the instance beyond this one statement.",
               related_scripts="04_statement_history.sql, ../lock-storm/README.md",
               table_purpose="Sessions blocked behind the runaway, plus temp-file volume per database."),
    sql_script("04", "04_statement_history",
               "Checks whether this statement shape has always been expensive or has recently regressed.",
               _pgss_guarded(sb.pgss_temp_and_io_heavy()),
               "Match on the query snippet. High temp_blks_written with a modest call count is a work_mem or statistics problem; a statement that is normally cheap and is expensive only right now is a plan regression worth a full deep-dive after the incident. A statement that has always been this expensive belongs on a reader, not on the writer.",
               required_privileges=PG_MONITOR_PLUS_PGSS,
               prerequisites="pg_stat_statements installed in the current database; the script prints a notice and exits cleanly if it is not.",
               related_scripts="../../performance/high-cpu/README.md",
               table_purpose="Statement history for temp-file and IO-heavy statements."),
    md_script("05", "05_stop_the_runaway_query",
              "Guarded runbook for stopping a runaway query with the smallest intervention that actually works, and for handling the open-transaction case correctly.",
              (
                  "## Before you stop anything\n"
                  "\n"
                  "Three things must be true, and all three come from script 02:\n"
                  "\n"
                  "1. You have captured `full_query_text` and posted it in the incident channel.\n"
                  "2. You know the owning service or human from `application_name` / `usename` /\n"
                  "   `client_addr`, and you have told them.\n"
                  "3. `backend_type` is `client backend`. If it is anything else, stop -- this is not\n"
                  "   an application query and signalling it is not your call.\n"
                  "\n"
                  + _cancel_vs_terminate_section() +
                  "\n"
                  "## Step 1 -- cancel\n"
                  "\n"
                  "```sql\n"
                  "SELECT pg_cancel_backend(<pid from script 02>);\n"
                  "```\n"
                  "\n"
                  "Re-run `02_target_backend_detail.sql`. Three possible outcomes:\n"
                  "\n"
                  "* **No rows.** The session is gone entirely (its client disconnected on error).\n"
                  "  Done -- go to verification.\n"
                  "* **State is `idle` or `idle in transaction (aborted)`.** The statement was\n"
                  "  cancelled and the connection survived, which is the intended result.\n"
                  "* **Still `active` with the same query_start.** The cancel has not taken effect.\n"
                  "  A backend inside certain long internal operations cannot be interrupted\n"
                  "  immediately; give it another 15 seconds before escalating.\n"
                  "\n"
                  "## Step 2 -- the open-transaction trap\n"
                  "\n"
                  "*Precondition: script 02 showed `txn_runtime` much larger than `query_runtime`.*\n"
                  "\n"
                  "The statement was only part of a longer transaction. Cancelling it leaves that\n"
                  "transaction OPEN, still holding its snapshot and every lock it had already\n"
                  "acquired -- so the blocking and the vacuum-horizon damage continue even though\n"
                  "the expensive statement has stopped. This surprises people constantly.\n"
                  "\n"
                  "Resolve it one of two ways:\n"
                  "\n"
                  "* Have the owning client issue `ROLLBACK` (preferred -- the application controls\n"
                  "  its own outcome), or\n"
                  "* Terminate the backend, per step 3, which rolls the transaction back for it.\n"
                  "\n"
                  "## Step 3 -- terminate, only if justified\n"
                  "\n"
                  "```sql\n"
                  "SELECT pg_terminate_backend(<pid from script 02>);\n"
                  "```\n"
                  "\n"
                  "Justified when: the cancel demonstrably failed, or the transaction must be rolled\n"
                  "back and its client cannot be reached. The financial-write safety gate above\n"
                  "applies in full if the statement touched `ledger_entries`, `wallets`,\n"
                  "`withdrawals`, `deposits`, `trades` or `orders`.\n"
                  "\n"
                  "Expect the rollback itself to take time for a statement that had already written\n"
                  "a lot -- the backend stays visible in `pg_stat_activity` while it unwinds, and\n"
                  "signalling it again does not speed that up.\n"
                  "\n"
                  "## Step 4 -- stop it coming straight back\n"
                  "\n"
                  "An unmodified retry reproduces this incident within minutes, so close the loop\n"
                  "before you close the incident:\n"
                  "\n"
                  "* Tell the owner explicitly not to retry as-is.\n"
                  "* If it was ad-hoc analytical work, point it at the reader endpoint.\n"
                  "* If it was application code, agree a role-level `statement_timeout` as a\n"
                  "  guardrail with that team (new sessions only; existing sessions unaffected):\n"
                  "\n"
                  "```sql\n"
                  "ALTER ROLE <role_name> SET statement_timeout = '30s';\n"
                  "ALTER ROLE <role_name> RESET statement_timeout;   -- revert step\n"
                  "```\n"
                  "\n"
                  "## Step 5 -- verify\n"
                  "\n"
                  "Re-run `03_collateral_damage.sql`. Sessions that were blocked behind the runaway\n"
                  "should now be draining. If they are not, a second blocker exists and the incident\n"
                  "continues in `../lock-storm/README.md`.\n"
              ),
              "Capture the query text first, cancel before terminating, and check the open-transaction trap in step 2 -- a successful cancel that leaves the transaction open is the most common false 'fixed' in this workflow.",
              safety=ELEVATED_RISK_SESSION,
              expected_impact="A cancel aborts the running statement and leaves the connection and any open transaction alive. A terminate ends the connection and rolls the whole transaction back.",
              required_privileges=INCIDENT_OPERATOR_PRIVS,
              prerequisites="Scripts 01-04 completed, the full query text captured, the owner identified, and backend_type confirmed as client backend.",
              execution_location=INCIDENT_TARGET_INSTANCE,
              expected_runtime="Seconds to signal; rollback of a large write transaction can take considerably longer.",
              related_scripts="02_target_backend_detail.sql, 03_collateral_damage.sql",
              table_purpose="Guarded actions: cancel the runaway, handle the open-transaction case, terminate if justified."),
]

# ---------------------------------------------------------------------------
# 7. application-timeouts
# ---------------------------------------------------------------------------
WORKFLOWS.append(_wf(
    slug="application-timeouts",
    title="Application Timeouts",
    summary=(
        "Services are reporting database timeouts -- statement timeouts, "
        "pool-acquisition timeouts, or client-side deadline expiry -- and the "
        "question is whether the database is actually slow, or whether a "
        "timeout is set too aggressively, or whether the bottleneck is in the "
        "pooler or the network. This workflow answers that question quickly, "
        "because the three causes have completely different fixes and only "
        "one of them is a database problem."
    ),
    symptoms=[
        "Application errors citing `canceling statement due to statement timeout` (SQLSTATE 57014) or a framework-level query timeout.",
        "Connection-pool acquisition timeouts with no corresponding database-side error at all.",
        "Timeouts concentrated in one service or one endpoint while everything else behaves normally.",
        "Timeouts that started immediately after a configuration change, a deployment, or a credential/role change.",
        "Retry storms visible as a high call count on a small set of statements.",
    ],
    business_impact=[
        "Timeouts on the order path surface to customers as failed placements or cancellations, and during volatility a failed cancel is a direct financial loss for the customer.",
        "Timeouts that the application handles by retrying multiply database load, so an aggressive timeout can be the cause of the slowness it is reacting to.",
        "Withdrawal and deposit flows that fail open on timeout risk double-processing; flows that fail closed strand customer funds. Both outcomes attract compliance attention.",
    ],
    root_causes=[
        "The database genuinely is slow: blocking, resource saturation, or a plan regression, and the timeout is doing its job.",
        "The timeout is set too aggressively for the query's honest runtime, so normal work is being killed.",
        "A role- or database-level timeout override that nobody remembers applying, making one role behave differently from another running the same query.",
        "Pool-acquisition timeouts rather than statement timeouts: the request never reached the database at all, so nothing is visible in database-side statistics.",
        "Network or pooler latency between the application and the database inflating the end-to-end deadline while server-side execution time stays fine.",
        "A lock wait, which looks identical to slowness from the application's side but needs a completely different fix.",
        "Connection exhaustion, which presents as a timeout in almost every client library.",
    ],
    investigation_strategy=[
        "Read the effective timeout settings on the server first -- statement_timeout, lock_timeout and idle_in_transaction_session_timeout.",
        "Check the role- and database-level overrides, because that is where surprising per-service differences almost always live.",
        "Check the session outcome counters for evidence of who is ending sessions and how.",
        "Check whether sessions are blocked, since a lock wait is the most common cause of a timeout that has nothing to do with query cost.",
        "Check connection headroom, because pool-acquisition timeouts caused by exhaustion never appear as database-side slowness at all.",
        "Decide which of the three worlds you are in -- database slow, timeout too tight, or never-reached-the-database -- and act accordingly.",
    ],
    prerequisites=[
        "`pg_monitor` role membership.",
        "The application's own timeout configuration: pool acquisition timeout, socket timeout, and any framework-level query deadline. Server-side settings alone cannot explain a client-side timeout.",
        "The exact error text and SQLSTATE from the application logs -- 57014 (statement timeout), 57P01 (terminated), and a pool-acquisition timeout are three entirely different incidents.",
    ],
    interpretation_guide=[
        "If the error is SQLSTATE 57014, the database killed the statement on purpose and the server-side timeout setting is the relevant configuration -- find which layer set it using script 02.",
        "If the application reports a timeout but the database shows no statement timeout and no long-running queries, the request likely never reached the database: suspect the pool, the proxy or the network.",
        "A statement_timeout of 0 for the affected role means the server is not the one timing out, so the deadline is client-side however the error is worded.",
        "Blocked sessions in script 04 mean the timeouts are lock waits in disguise; tuning queries will not help and the lock-storm workflow will.",
        "Connection utilization near the ceiling in script 05 explains pool-acquisition timeouts completely, and that is a connection incident rather than a query one.",
        "Timeouts that affect exactly one role while another role runs the same query successfully is almost always a pg_db_role_setting override -- script 02 finds it in seconds.",
    ],
    remediation_immediate=[
        "If the database is genuinely slow, stop reading this workflow and go fix the slowness through the lock-storm, runaway-query or latency workflow -- the timeout is a messenger.",
        "If the timeout is too tight for honest work, agree a temporary role-level increase with the owning team and record it as an incident-scoped change with a revert step.",
        "If it is a pool-acquisition timeout, treat it as connection exhaustion and use that workflow.",
        "Confirm the application's retry behaviour: unbounded retries on timeout turn a small slowdown into a self-sustaining incident, and capping them is often the single most effective immediate action.",
    ],
    remediation_short_term=[
        "Set explicit, intentional per-role timeouts rather than inheriting a cluster default: a trading API role and a reconciliation role should not share one statement_timeout.",
        "Set `lock_timeout` alongside `statement_timeout` so lock waits fail fast and distinguishably, instead of consuming the entire statement budget and reporting as generic slowness.",
        "Align client-side deadlines with server-side timeouts so the two layers cannot disagree about who owns the failure.",
    ],
    remediation_long_term=[
        "Document a timeout budget per service tier -- trading path, funds movement, reporting -- and enforce it in role configuration rather than in scattered application settings.",
        "Instrument the application to distinguish pool-acquisition time from query execution time, so this triage takes seconds next time instead of minutes.",
        "Require exponential backoff with jitter and a retry cap on every database call, so retries dampen an incident instead of amplifying it.",
    ],
    production_safety=[
        "Scripts 01-05 are read-only and safe to run at any time.",
        "Script 06 changes role-level configuration affecting live traffic; read it fully and get the owning team's agreement before applying anything.",
        "Never raise or remove a timeout globally to make errors stop. Timeouts are the mechanism that prevents one slow statement from consuming every connection, and removing them converts a visible incident into a silent, much larger one.",
    ],
    escalation_criteria=[
        "Timeouts affect funds-movement flows (deposits, withdrawals, settlement) -- escalate to treasury and compliance immediately, because the failure mode determines whether funds are stranded or at risk of double-processing.",
        "The application cannot distinguish pool-acquisition timeouts from statement timeouts, so the investigation cannot be completed from the database side -- escalate to the owning service to add that instrumentation.",
        "Server-side execution times are healthy but end-to-end latency is not, which points at the network or pooler -- escalate to the platform team.",
        "A timeout change is requested on a role used by settlement or reconciliation -- that requires named approval, not an on-call judgement call.",
    ],
    related_issues=[
        "../production-triage/README.md",
        "../sudden-latency-spike/README.md",
        "../lock-storm/README.md",
        "../connection-exhaustion/README.md",
        "../../connections/connection-exhaustion/README.md",
        "../../concurrency-and-locking/blocked-queries/README.md",
    ],
    aurora_notes=[
        "On Aurora, cluster-wide defaults for statement_timeout and lock_timeout come from the DB cluster parameter group rather than postgresql.conf, and ALTER SYSTEM is not available for them -- role-level ALTER ROLE ... SET remains the correct in-database mechanism for a per-service override.",
        "RDS Proxy imposes its own connection borrow timeout; when a proxy is in the path, a client-reported timeout may have expired while waiting for the proxy to lend a database connection, and nothing about it will ever appear in this database's statistics.",
        "Aurora failovers cause a short burst of connection errors and timeouts by design; before treating a brief timeout spike as a workload problem, check the cluster events for a failover in the same minute.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_effective_timeout_settings",
               "Reads the timeout and concurrency settings this connection actually resolved to.",
               sb.key_settings_snapshot(),
               "Check statement_timeout, lock_timeout and idle_in_transaction_session_timeout. A statement_timeout of 0 means the server is not cancelling anything, so any timeout the application reports is client-side however its error message is worded. Remember these are YOUR session's values; script 02 shows what other roles get.",
               related_scripts="02_role_and_database_overrides.sql",
               table_purpose="Effective values of the timeout and concurrency settings."),
    sql_script("02", "02_role_and_database_overrides",
               "Shows the per-role and per-database setting overrides that explain why one service times out while another does not.",
               _role_and_database_setting_overrides(),
               "This is where surprising timeout behaviour almost always hides. A role with statement_timeout set aggressively, or set to 0, explains an entire class of incident instantly -- and an override nobody remembers applying is a very common root cause after a role or credential change.",
               related_scripts="03_session_outcome_counters.sql",
               table_purpose="Role-level and database-level GUC overrides from pg_db_role_setting."),
    sql_script("03", "03_session_outcome_counters",
               "Checks how sessions are actually ending, which separates server-side cancellation from client-side abandonment.",
               _session_outcome_counters(),
               "Rising sessions_abandoned means clients are giving up and disconnecting -- a client-side deadline, not a server-side timeout. Rising sessions_fatal means the server is ending them. A high pct_rollback alongside either suggests transactions are failing rather than completing, which is worth correlating with the application's error taxonomy.",
               related_scripts="04_blocking_and_waits.sql",
               table_purpose="Abandoned, fatal and killed session counters plus rollback ratio."),
    sql_script("04", "04_blocking_and_waits",
               "Checks whether the timeouts are lock waits in disguise -- the most common cause of a timeout that has nothing to do with query cost.",
               _combine(sb.blocked_sessions(), sb.wait_events_summary()),
               "Any meaningful blocked-session count means these timeouts are lock waits. Tuning queries or relaxing timeouts will not help; clearing the blocker will. If lock_timeout is unset, a blocked statement consumes its entire statement_timeout budget before failing, which is why lock waits so often present as generic slowness.",
               related_scripts="05_connection_headroom.sql, ../lock-storm/README.md",
               table_purpose="Blocked sessions plus the current wait-event distribution."),
    sql_script("05", "05_connection_headroom",
               "Checks whether the timeouts are actually pool-acquisition failures caused by connection exhaustion.",
               _combine(sb.max_connections_headroom(), sb.connections_by_application_and_user()),
               "High pct_utilized means requests are timing out while waiting for a connection and never reaching the database at all -- which is why nothing appears in the query statistics. That is a connection incident; the per-application breakdown names the service holding the slots.",
               related_scripts="06_timeout_mitigation_actions.md, ../connection-exhaustion/README.md",
               table_purpose="Connection headroom plus per-application connection attribution."),
    md_script("06", "06_timeout_mitigation_actions",
              "Guarded runbook for the timeout-specific actions: adjusting role-level timeouts safely, adding lock_timeout, and capping retries.",
              (
                  "## First, decide which of the three worlds you are in\n"
                  "\n"
                  "| Evidence | World | Correct action |\n"
                  "|---|---|---|\n"
                  "| Script 04 shows blocked sessions | The database is blocked | Clear the blocker: `../lock-storm/README.md`. Do not touch timeouts. |\n"
                  "| Script 05 shows utilization near the ceiling | Requests never reach the database | Treat as connection exhaustion: `../connection-exhaustion/README.md`. |\n"
                  "| Neither, and server-side execution times look healthy | The timeout is misconfigured, or the latency is outside the database | Continue below. |\n"
                  "\n"
                  "Changing a timeout while the real cause is blocking or exhaustion hides the\n"
                  "incident without fixing it, which is strictly worse than leaving it visible.\n"
                  "\n"
                  "## Action A -- adjust a role-level statement timeout\n"
                  "\n"
                  "*Precondition: script 02 shows the role's current value, and the owning team\n"
                  "agrees the honest runtime of their query genuinely exceeds it.*\n"
                  "\n"
                  "```sql\n"
                  "-- Applies to NEW sessions of this role only. Existing pooled sessions keep the\n"
                  "-- old value until they are recycled, so expect a gradual rather than an instant\n"
                  "-- change in behaviour.\n"
                  "ALTER ROLE <role_name> SET statement_timeout = '15s';\n"
                  "\n"
                  "-- Revert step, to be executed once the underlying query is fixed:\n"
                  "ALTER ROLE <role_name> RESET statement_timeout;\n"
                  "```\n"
                  "\n"
                  "Raise it to the smallest value that lets honest work complete, and record the\n"
                  "revert step and its owner in the incident channel at the same time. An\n"
                  "incident-scoped timeout increase that nobody reverts becomes next quarter's\n"
                  "connection-exhaustion incident.\n"
                  "\n"
                  "Never set `statement_timeout = 0` on an application role to make errors stop.\n"
                  "That removes the only mechanism preventing one pathological statement from\n"
                  "occupying a connection indefinitely.\n"
                  "\n"
                  "## Action B -- add a lock timeout so lock waits fail fast and distinguishably\n"
                  "\n"
                  "*Precondition: script 04 showed lock waits contributing to the timeouts.*\n"
                  "\n"
                  "Without `lock_timeout`, a statement blocked on a lock burns its entire\n"
                  "`statement_timeout` budget and then reports as a generic slow query -- which is\n"
                  "exactly why this class of incident is so often misdiagnosed:\n"
                  "\n"
                  "```sql\n"
                  "ALTER ROLE <role_name> SET lock_timeout = '2s';\n"
                  "ALTER ROLE <role_name> RESET lock_timeout;   -- revert step\n"
                  "```\n"
                  "\n"
                  "Set `lock_timeout` well below `statement_timeout` so the two failure modes are\n"
                  "distinguishable in the application's error logs.\n"
                  "\n"
                  "## Action C -- cap retries (application side, highest leverage)\n"
                  "\n"
                  "This is not a database change, and it is frequently the single most effective\n"
                  "action available. Unbounded retries on timeout multiply load on a database that\n"
                  "is already struggling, which is how a 200ms hiccup becomes a 20-minute incident.\n"
                  "\n"
                  "Ask the owning service for: exponential backoff with jitter, a hard retry cap,\n"
                  "and a circuit breaker that stops retrying entirely once the error rate crosses a\n"
                  "threshold.\n"
                  "\n"
                  "## Action D -- protect funds-movement flows\n"
                  "\n"
                  "Timeouts on deposit, withdrawal and settlement paths need an explicit decision\n"
                  "about failure semantics, not just a number:\n"
                  "\n"
                  "* Failing **open** (proceeding on timeout) risks double-processing a movement.\n"
                  "* Failing **closed** (rejecting on timeout) strands customer funds temporarily.\n"
                  "\n"
                  "Neither is a database setting, and neither is an on-call decision. Escalate to\n"
                  "treasury and compliance and record the chosen semantics in the incident log.\n"
                  "\n"
                  "## Verify\n"
                  "\n"
                  "Re-run `03_session_outcome_counters.sql` a few minutes after any change and\n"
                  "compare the deltas. Falling sessions_abandoned and sessions_fatal means the\n"
                  "change is working; unchanged counters mean you changed the wrong layer.\n"
              ),
              "Use the three-worlds table first -- it is the whole point of this file. Only continue past it when blocking and connection exhaustion have both been ruled out, because a timeout change is the wrong fix for either of those.",
              safety=ELEVATED_RISK_CONFIG,
              expected_impact="Role-level timeout changes alter how the affected service's statements fail, for new sessions only. No data is modified by any statement in this file.",
              required_privileges="Membership in the target role, or a role with CREATEROLE/ownership over it, is required to run ALTER ROLE ... SET. On Aurora this is typically `rds_superuser`.",
              prerequisites="Scripts 01-05 completed, blocking and connection exhaustion ruled out, and the owning team's agreement for any change plus a named owner for the revert step.",
              execution_location="Writer instance (role-level settings are cluster-wide configuration stored in the catalog).",
              expected_runtime="Seconds; behavioural change appears as pooled sessions are recycled.",
              related_scripts="02_role_and_database_overrides.sql, 04_blocking_and_waits.sql, 05_connection_headroom.sql",
              table_purpose="Guarded actions: adjust role timeouts, add lock_timeout, cap retries, decide funds-flow semantics."),
]

# ---------------------------------------------------------------------------
# 8. post-deployment-incident
# ---------------------------------------------------------------------------
WORKFLOWS.append(_wf(
    slug="post-deployment-incident",
    title="Post-Deployment Incident",
    summary=(
        "Something broke immediately after a release, and the question is "
        "whether the deployment caused it and whether to roll back now. "
        "Time pressure here is extreme and the bias should be toward "
        "rollback -- but a schema migration may have made rollback unsafe, "
        "so this workflow establishes what the deployment actually did to "
        "the database before that decision is made."
    ),
    symptoms=[
        "Errors, latency or lock waits that begin within minutes of a rollout, with a clear before-and-after in the graphs.",
        "A new application_name, or a sharp change in session count, appearing at the deployment timestamp.",
        "A migration statement visible in pg_stat_activity, running or waiting on a lock.",
        "New invalid indexes left behind by a concurrent index build that failed during the release.",
        "A query shape that has never been seen before suddenly appearing in the top statements by call count.",
    ],
    business_impact=[
        "Deployment-induced incidents hit the newest, least-proven code path on the most business-critical system, often during business hours when trading volume is highest.",
        "A migration that is half-applied is far more dangerous than one that never ran: the schema and the application disagree, and financial writes can fail or, worse, succeed against the wrong shape.",
        "Rollback decisions made without knowing what the migration did to the database are how a ten-minute incident becomes a data-integrity investigation.",
    ],
    root_causes=[
        "A schema migration taking or waiting for a strong lock on a hot table, blocking the application behind it.",
        "A new or changed query with no supporting index, turning a fast lookup into a sequential scan on a large table.",
        "A concurrent index build that failed partway, leaving an invalid index that consumes storage and slows writes without ever being used.",
        "A connection-pool configuration change that multiplied the fleet's connection count.",
        "An ORM upgrade changing generated SQL, isolation level, or transaction boundaries in ways nobody reviewed.",
        "A new code path issuing many small queries where one set-based query was intended -- the classic N+1 pattern arriving in production.",
        "Statistics invalidated by a large data backfill run as part of the release, so the planner's estimates are suddenly wrong.",
    ],
    investigation_strategy=[
        "Attribute current workload by application and session age, so the newly deployed fleet is visible as a distinct group with a distinct arrival time.",
        "Check immediately for migration DDL holding or waiting for locks -- this is both the most common and the most damaging deployment failure mode.",
        "Check for in-progress or failed index builds, including invalid indexes left behind.",
        "Look for new or newly frequent query shapes in pg_stat_statements.",
        "Check statistics freshness and scan patterns on the tables the release touched, since a backfill can invalidate the planner's assumptions instantly.",
        "Make the rollback decision explicitly, using the schema-compatibility criteria in the runbook rather than instinct.",
    ],
    prerequisites=[
        "The exact deployment timestamp and the list of services included in it -- without this, correlation is guesswork.",
        "The migration list from the release, including whether each migration is reversible.",
        "`pg_monitor` role membership, plus `pg_stat_statements` for the query-shape check.",
        "A direct line to the deploying team, who must be part of the rollback decision rather than informed after it.",
    ],
    interpretation_guide=[
        "Session groups whose newest_session_started clusters at the deployment time identify the new fleet. Comparing its blocked_count and longest_active_query against unchanged services isolates the effect of the release in one query.",
        "A migration statement with granted = false is the highest-priority finding in this workflow: the DDL is waiting, and every query that arrived after it is queued behind its lock request, so a single waiting ALTER TABLE presents as a total outage on that table.",
        "Invalid indexes dated to the release mean a concurrent build failed. They are never used by the planner but still slow every write to the table, so they must be cleaned up deliberately.",
        "A query shape with a high call count that did not exist before the release is the new code path; if its mean time is small but its call count is enormous, you are looking at an N+1 pattern.",
        "A table with a very high pct_modified_since_analyze right after a release means a backfill ran and statistics have not caught up, which can flip plans on statements that were fine an hour ago.",
        "If nothing in the database correlates with the deployment, say so clearly -- a release can coincide with an unrelated incident, and anchoring on the deployment wastes the response.",
    ],
    remediation_immediate=[
        "If a migration is blocking traffic, cancel the migration statement rather than the application transactions it is waiting on -- a cancelled DDL rolls back cleanly with no data change.",
        "If the application code is the problem and the migration is reversible or was never applied, roll back the deployment now. Rollback is almost always the fastest route to recovery.",
        "If the migration is applied and not reversible, do not roll back blindly: a rollback to code that does not understand the new schema is a data-integrity risk, not a recovery.",
        "If a missing index is the cause and rollback is unavailable, build it concurrently per the schema-changes workflow rather than with a blocking build during an incident.",
    ],
    remediation_short_term=[
        "Clean up any invalid indexes left behind by failed concurrent builds, in a change-managed window.",
        "Analyse the specific tables affected by a release backfill so the planner's estimates catch up with the new data.",
        "Add the missing index the new query shape needs, built concurrently.",
        "Re-run the failed migration with `lock_timeout` set and using the concurrent, lock-light patterns.",
    ],
    remediation_long_term=[
        "Make every migration follow the expand/contract pattern so that application and schema are always compatible in both directions and rollback is never gated on a migration.",
        "Require a lock-risk review for every migration touching a hot table, stating the expected lock mode and duration before it ships.",
        "Add a post-deploy database canary: compare top query shapes, lock waits and error rates for a fixed window after each release, and fail the rollout automatically on a regression.",
    ],
    production_safety=[
        "Scripts 01-05 are read-only and safe to run at any point during the incident.",
        "Script 06 is a decision runbook containing guarded actions; read it fully, and note that its most important content is the decision criteria rather than the statements.",
        "Never roll back application code past an applied, non-reversible migration without an explicit schema-compatibility check. That single mistake causes more data-integrity incidents than the deployments themselves.",
    ],
    escalation_criteria=[
        "A migration is half-applied on a financial table -- escalate to database engineering leadership and treasury immediately; do not attempt to complete or reverse it unilaterally.",
        "Rollback is blocked by an applied non-reversible migration while customer impact continues -- this requires a joint decision between database engineering and the deploying team, with a named decision owner.",
        "The incident affects deposits, withdrawals or settlement -- involve compliance from the start, not after resolution.",
        "The deployment cannot be correlated with any database-side change yet impact continues -- broaden the investigation rather than continuing to focus on the release.",
    ],
    related_issues=[
        "../production-triage/README.md",
        "../lock-storm/README.md",
        "../sudden-latency-spike/README.md",
        "../application-timeouts/README.md",
        "../../schema-changes/failed-index-build/README.md",
        "../../database-health/comprehensive-health-check/README.md",
    ],
    aurora_notes=[
        "Aurora does not make DDL any cheaper than community PostgreSQL: an ALTER TABLE that needs an AccessExclusiveLock still blocks all access to the table for its duration, and the fast-storage architecture does not change lock semantics at all.",
        "A failed CREATE INDEX CONCURRENTLY leaves an invalid index on Aurora exactly as it does on community PostgreSQL, and that index still consumes cluster-volume storage while being useless to the planner.",
        "Aurora's cluster-volume storage does not shrink when an index is dropped -- space is reused, not returned -- so cleaning up after a failed release recovers usable capacity, not billed storage.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_workload_by_application_and_session_age",
               "Attributes the current workload to each service and shows when its sessions were established, making the newly deployed fleet visible.",
               _workload_by_application_with_session_age(),
               "Look for a group whose newest_session_started (and often oldest_session_started) matches the deployment timestamp: that is the new fleet. Compare its blocked_count, active_count and longest_active_query against the services that did not change -- the difference is the effect of the release, isolated in one query.",
               related_scripts="02_migration_lock_waits.sql",
               table_purpose="Workload by application and user, including session establishment times."),
    sql_script("02", "02_migration_lock_waits",
               "Checks for migration DDL holding or waiting for strong locks -- the most common and most damaging deployment failure mode.",
               _combine(sb.ddl_lock_waits(), sb.blocked_sessions()),
               "A DDL row with granted = false means the migration is itself waiting, and every query that arrived after it is queued behind its lock request. That is why a single waiting ALTER TABLE looks exactly like a total outage on that table. The blocked list quantifies the blast radius for the incident channel.",
               related_scripts="03_index_build_state.sql, ../lock-storm/README.md",
               table_purpose="DDL-strength lock waits plus the sessions queued behind them."),
    sql_script("03", "03_index_build_state",
               "Checks in-progress index builds and any invalid indexes left behind by a build that failed during the release.",
               _combine(sb.create_index_progress(), sb.invalid_indexes()),
               "A build parked in a 'waiting for' phase is not slow because of IO -- it is waiting for older transactions to finish, and current_locker_pid names the backend it is waiting on. Invalid indexes dated to this release mean a concurrent build failed: they are never used by the planner yet still slow every write to the table.",
               related_scripts="04_new_query_shapes.sql, ../../schema-changes/failed-index-build/README.md",
               table_purpose="Index build progress plus invalid indexes from failed builds."),
    sql_script("04", "04_new_query_shapes",
               "Looks for new or newly frequent statements, which is how a changed code path announces itself at the database.",
               _pgss_guarded(sb.pgss_top_by_calls()),
               "A statement shape with a very high call count and a small mean execution time that nobody recognizes is the classic N+1 pattern arriving in production. Compare against a saved pre-deployment capture if you have one -- this ranking is far more useful as a diff than as an absolute reading.",
               required_privileges=PG_MONITOR_PLUS_PGSS,
               prerequisites="pg_stat_statements installed in the current database; the script prints a notice and exits cleanly if it is not.",
               related_scripts="05_statistics_and_scan_regression.sql",
               table_purpose="Top statements by call count, to spot newly introduced query shapes."),
    sql_script("05", "05_statistics_and_scan_regression",
               "Checks whether a release backfill invalidated planner statistics, or whether a new access pattern is driving sequential scans on large tables.",
               _combine(sb.statistics_freshness(), sb.sequential_scan_heavy_tables()),
               "A high pct_modified_since_analyze immediately after a release means a backfill ran and the planner's row estimates are now wrong, which can flip plans on statements that were fine an hour ago. A large table with a high seq_tup_read and a low idx_scan is the signature of a new query with no supporting index.",
               related_scripts="06_rollback_decision_runbook.md",
               table_purpose="Statistics staleness plus sequential-scan-heavy tables."),
    md_script("06", "06_rollback_decision_runbook",
              "The rollback decision itself: the schema-compatibility criteria that determine whether rolling back is recovery or a second incident, plus the guarded actions for each branch.",
              (
                  "## The decision this file exists for\n"
                  "\n"
                  "Rollback is usually the fastest path to recovery, and the default bias should be\n"
                  "toward it. The one thing that can make rollback *worse* than the incident is a\n"
                  "schema migration that has already been applied. Answer this question before\n"
                  "anything else:\n"
                  "\n"
                  "> **Can the previous application version run correctly against the schema as it\n"
                  "> exists right now?**\n"
                  "\n"
                  "| Migration state | Rollback safe? | Action |\n"
                  "|---|---|---|\n"
                  "| No migration in this release | Yes | Roll back now. |\n"
                  "| Migration is additive only (new nullable column, new table, new index) | Yes | Roll back now; the old code simply ignores the additions. |\n"
                  "| Migration never started, or is still waiting on a lock | Yes | Cancel the DDL (Action A), then roll back. |\n"
                  "| Migration applied, and is reversible with a tested down-migration | Usually | Roll back code first, then reverse the migration deliberately -- never both at once. |\n"
                  "| Migration applied and destructive (column or table dropped, type narrowed, constraint tightened) | **No** | Do NOT roll back. Fix forward, and escalate now. |\n"
                  "| Migration half-applied on a financial table | **No** | Stop. Escalate to database engineering leadership and treasury immediately. |\n"
                  "\n"
                  "Get the answer from the deploying team's migration list, not from memory. If\n"
                  "nobody can say confidently which row applies, that uncertainty is itself an\n"
                  "escalation trigger.\n"
                  "\n"
                  + _cancel_vs_terminate_section() +
                  "\n"
                  "## Action A -- cancel a migration that is blocking traffic\n"
                  "\n"
                  "*Precondition: script 02 shows a DDL statement with `granted = false` and other\n"
                  "sessions queued behind it.*\n"
                  "\n"
                  "Cancel the DDL, not the application transaction it is waiting on. A DDL statement\n"
                  "that has not obtained its lock has changed no data, so cancelling it is clean and\n"
                  "instantly drains the queue behind it:\n"
                  "\n"
                  "```sql\n"
                  "SELECT pg_cancel_backend(<migration pid from script 02>);\n"
                  "```\n"
                  "\n"
                  "Then tell the deploying team not to retry until the migration has a `lock_timeout`\n"
                  "and uses the concurrent, lock-light pattern -- an immediate retry recreates this\n"
                  "incident exactly, usually within a minute.\n"
                  "\n"
                  "## Action B -- roll back the application\n"
                  "\n"
                  "*Precondition: the table above says rollback is safe.*\n"
                  "\n"
                  "Roll back through your normal deployment mechanism. From the database side, watch\n"
                  "`01_workload_by_application_and_session_age.sql` as the old fleet reconnects: the\n"
                  "new session group should drain and the previous one reappear. Confirm blocked_count\n"
                  "returns to zero for the affected services before declaring recovery.\n"
                  "\n"
                  "## Action C -- fix forward when rollback is unsafe\n"
                  "\n"
                  "*Precondition: the table above says rollback is not safe.*\n"
                  "\n"
                  "Options, in order of preference:\n"
                  "\n"
                  "1. Disable the offending code path with a feature flag. Fastest, and fully\n"
                  "   reversible.\n"
                  "2. Add the missing index the new query needs -- built concurrently, never with a\n"
                  "   blocking build during an incident. Follow\n"
                  "   `../../schema-changes/failed-index-build/README.md`.\n"
                  "3. Analyse the specific tables a backfill touched, so the planner's estimates\n"
                  "   catch up. Target the named tables from script 05; do not analyse the whole\n"
                  "   database during an incident.\n"
                  "\n"
                  "## Action D -- clean up after a failed index build\n"
                  "\n"
                  "*Precondition: script 03 listed invalid indexes created during this release.*\n"
                  "\n"
                  "An invalid index is never used by the planner but still consumes storage and slows\n"
                  "every write to its table, so it must be removed -- deliberately, and normally in a\n"
                  "change-managed window rather than mid-incident. The concurrent form avoids taking\n"
                  "a blocking lock on the table:\n"
                  "\n"
                  "```sql\n"
                  "-- Verify the index is genuinely invalid and genuinely from this release first,\n"
                  "-- using script 03. Dropping the wrong index during an incident is its own outage.\n"
                  "DROP INDEX CONCURRENTLY <schema>.<index_name>;\n"
                  "```\n"
                  "\n"
                  "On Aurora, the space is returned to the cluster volume for reuse but the volume\n"
                  "itself does not shrink, so this recovers usable capacity rather than billed\n"
                  "storage.\n"
                  "\n"
                  "## Record the decision\n"
                  "\n"
                  "Write down which row of the table applied, who confirmed the migration state, and\n"
                  "what was decided. Post-deployment incidents are re-litigated in review more than\n"
                  "any other kind, and the migration-state evidence is what makes that review useful\n"
                  "instead of speculative.\n"
              ),
              "The decision table at the top is the point of this file. Answer the schema-compatibility question before considering any action -- rolling back past an applied destructive migration causes a data-integrity incident that is far more expensive than the outage you are trying to end.",
              safety=ELEVATED_RISK_SESSION,
              expected_impact="Cancelling a waiting migration rolls that DDL back cleanly with no data change. Rollback and index cleanup are change-managed operations with their own, separately documented impact.",
              required_privileges=INCIDENT_OPERATOR_PRIVS + " Dropping an index additionally requires ownership of the index or its table.",
              prerequisites="Scripts 01-05 completed, the migration list and its reversibility confirmed with the deploying team, and a named decision owner for the rollback call.",
              execution_location=INCIDENT_TARGET_INSTANCE,
              expected_runtime="Seconds to cancel; a concurrent index drop takes proportionally longer on a large table.",
              related_scripts="02_migration_lock_waits.sql, 03_index_build_state.sql, 05_statistics_and_scan_regression.sql",
              table_purpose="Rollback decision criteria plus guarded actions: cancel a migration, roll back, fix forward, clean up."),
]

# ---------------------------------------------------------------------------
# 9. production-triage  (the flagship rapid-response checklist)
# ---------------------------------------------------------------------------
WORKFLOWS.append(_wf(
    slug="production-triage",
    title="Production Triage -- Rapid Response Checklist",
    summary=(
        "The single checklist to run, start to finish, during ANY production "
        "incident on this cluster before deciding what to do next. Ten "
        "read-only scripts, in a fixed order, that take a complete picture of "
        "the database in a few minutes: cluster role, session load, wait "
        "events, blocking, long queries, long transactions, connection "
        "headroom, top statements, vacuum state, and storage. Every other "
        "workflow in this category answers a specific question; this one "
        "tells you which question to ask, and leaves behind the snapshot that "
        "the post-incident review will need."
    ),
    symptoms=[
        "Any page against this database cluster, from any source, with any symptom.",
        "A vague or multi-symptom report ('things feel slow', 'some errors', 'the dashboard looks wrong') that does not map cleanly to one workflow yet.",
        "Several teams reporting different symptoms at once, which usually means one shared cause rather than several independent problems.",
        "A handover to a second responder who needs the full current state of the database in one pass rather than a narrative.",
    ],
    business_impact=[
        "Triage speed is the largest controllable factor in the duration of an exchange incident: the database is the shared dependency of order entry, wallets, the ledger and settlement, so every minute of misdirected investigation is a minute of customer impact across all of them.",
        "Acting on a guess -- terminating sessions, failing over, restarting a pooler -- without this snapshot routinely adds a second, self-inflicted incident on top of the first.",
        "The snapshot this checklist produces is the only evidence the post-incident review will have: pg_stat_activity retains nothing once sessions end, and lock waits vanish the moment they clear.",
    ],
    root_causes=[
        "Not applicable as a cause category -- this workflow is the diagnostic entry point. Its output identifies which specific workflow owns the root cause.",
        "In practice the checklist resolves to one of: blocking or lock contention, resource saturation, connection exhaustion, a runaway or regressed query, replication or failover, or a cause outside the database entirely.",
    ],
    investigation_strategy=[
        "Run all ten scripts in numeric order, start to finish, before deciding anything. The order is deliberate: it goes from cluster-wide facts to progressively narrower detail, so each script is interpreted in the context the previous one established.",
        "Do not skip ahead because a symptom 'obviously' matches a workflow. The most expensive incidents in an exchange are the ones where the obvious explanation was a symptom of something else, and skipping the checklist is how that happens.",
        "Do not stop early when you find something interesting. Finish all ten: compound incidents (a lock storm that has caused connection exhaustion, a slow query that has delayed vacuum) are common, and the second finding changes the order of the fixes.",
        "Capture the output of every script into the incident channel or a file as you go. This is your forensic record, and most of it is unreproducible ten minutes later.",
        "Route on the evidence: Lock-dominated waits and blocking go to lock-storm; connection utilization at the ceiling goes to connection-exhaustion; one dominant statement goes to runaway-query; a cluster-role surprise goes to failover investigation; broad latency with no single cause goes to sudden-latency-spike.",
        "Only after all ten scripts, choose the specific workflow, and take the first action from that workflow's guarded runbook -- not from this one, which deliberately contains no remediation at all.",
    ],
    prerequisites=[
        "`pg_monitor` (or `pg_read_all_stats`) role membership, and CONNECT on the target database. Nothing more: this checklist is deliberately the lowest-privilege, lowest-prerequisite entry point in the entire toolkit.",
        "`pg_stat_statements` for script 08 only; it prints a notice and continues cleanly if the extension is absent, so a missing extension never stops the checklist.",
        "A connection to the instance you are investigating -- ideally the writer, since several scripts describe instance-local state that differs between writer and readers.",
        "Somewhere to paste the output: an incident channel, a scratch file, or a transcript. Do not rely on scrollback.",
    ],
    interpretation_guide=[
        "Script 01 (cluster role) first, always: if you are not on the instance you think you are on, every subsequent result is being read about the wrong machine.",
        "Script 02 sizes the incident. An active session count around or above the instance's vCPU count means work is queueing for CPU; a large idle-in-transaction population means an application is leaking transactions; a normal profile despite a live report means the problem may not be in the database at all.",
        "Script 03 (wait events) is the single highest-signal result in the checklist. Lock-dominated means blocking; IO-dominated means resource pressure; LWLock or IPC means internal contention; few or no waits alongside many active sessions means genuine CPU-bound work.",
        "Script 04 is decisive when non-empty: any meaningful blocked-session count makes this a blocking incident first, whatever else the other scripts show, because nothing else can be fixed while the graph is stalled.",
        "Scripts 05 and 06 distinguish a long-running query from a long-running transaction. They are different problems: a long query costs resources; a long transaction holds the vacuum horizon and locks even when it is idle, which is often the quieter and more damaging of the two.",
        "Script 07 tells you how much time you have. Utilization near the ceiling means the incident will shortly become an availability incident regardless of its original cause, which raises the priority of every other finding.",
        "Script 08 attributes cumulative cost to specific statements, which no instantaneous snapshot can do -- rank by total time, not by mean.",
        "Script 09 explains the slow-burn causes: dead tuples accumulating because vacuum cannot advance past a long transaction, or vacuum workers competing with peak traffic.",
        "Script 10 rarely explains a sudden incident, but it catches the ones that are actually capacity problems, and it is the cheapest place to notice unbounded table growth before it becomes its own page.",
        "If all ten scripts look normal and the symptom persists, that is a genuine and valuable result: say so explicitly and redirect the investigation to the application, the pooler or the network rather than continuing to search the database.",
    ],
    remediation_immediate=[
        "None from this workflow by design. It contains no remediation whatsoever -- its only output is an accurate picture and a routing decision.",
        "Take the first action from the guarded runbook of the specific workflow this checklist routes you to, so the action is taken with that workflow's preconditions and safety gates in force.",
    ],
    remediation_short_term=[
        "Follow the short-term remediation of whichever workflow this checklist routed you to.",
        "Save the checklist output into the incident record while it is still accurate; the follow-up work is far cheaper when the evidence survives.",
    ],
    remediation_long_term=[
        "Automate this checklist as a scheduled snapshot (see the automation category) so a pre-incident baseline exists for comparison -- 'is this number normal' is otherwise the slowest question in every incident.",
        "Use repeated incidents to tune the checklist itself: if a step consistently produces nothing for your workload, and another question consistently matters, change the checklist rather than working around it.",
        "Train every on-call engineer to run these ten scripts before proposing any action, so triage discipline does not depend on who happens to be paged.",
    ],
    production_safety=[
        "Every script in this checklist is read-only and safe to run even during a live incident with no prior investigation -- that is the entire design goal of this workflow.",
        "No script here modifies data, takes anything beyond a brief catalog lock, cancels or terminates a session, changes configuration, or depends on an operator editing it first. All ten can be run blind, in order, by anyone with pg_monitor.",
        "The only extension-dependent script (08) is guarded, so a missing pg_stat_statements prints a notice and the checklist continues rather than erroring out mid-incident.",
        "All remediation deliberately lives elsewhere. If you find yourself wanting to act from inside this workflow, that is the signal that you have identified the specific workflow you should be in.",
    ],
    escalation_criteria=[
        "The checklist cannot be completed because the database will not accept a connection -- escalate immediately and switch to the database-unavailable workflow and the disaster-recovery assessment in parallel.",
        "Script 01 shows a cluster role you did not expect (a writer that is now a reader) -- escalate on the failover track before interpreting anything else, because the topology changed underneath the incident.",
        "The checklist shows several independent anomaly classes at once -- treat it as a compound incident, declare a major incident, and assign a separate owner per track rather than working them sequentially.",
        "Order entry, deposits, withdrawals or settlement are affected -- escalate to treasury and compliance in parallel with the technical response, at the moment you know, not after resolution.",
        "All ten scripts are unremarkable while customer impact continues -- escalate outward to the application, platform and network teams; a clean database snapshot is strong evidence and should redirect the whole response.",
    ],
    related_issues=[
        "../database-unavailable/README.md",
        "../sudden-latency-spike/README.md",
        "../high-cpu/README.md",
        "../connection-exhaustion/README.md",
        "../lock-storm/README.md",
        "../runaway-query/README.md",
        "../application-timeouts/README.md",
        "../post-deployment-incident/README.md",
        "../../database-health/comprehensive-health-check/README.md",
        "../../replication-and-ha/failover-investigation/README.md",
    ],
    aurora_notes=[
        "Script 01 is Aurora-aware and matters more here than on community PostgreSQL: every Aurora reader reports pg_is_in_recovery() = true permanently, and the writer endpoint is a DNS record that moves during failover, so confirming which instance answered is a genuine finding rather than a formality.",
        "Several of these views are instance-local (sessions, locks, waits, IO), so running the checklist on a reader describes that reader only. During a cluster-wide incident, run it on the writer first, then on the affected reader.",
        "The database has no visibility into instance CPU, storage IOPS or network throughput -- pair this checklist with the CloudWatch metrics and the Performance Insights wait-event breakdown for the same window, which together cover what SQL cannot see.",
        "Aurora's storage layer grows in increments and never shrinks, so script 10's sizes describe logical object size; billed cluster-volume usage is a CloudWatch value (VolumeBytesUsed), not a SQL one.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_cluster_database_status",
               "Step 1 of 10: confirms whether this connection is on the writer or a reader, and reports Aurora's cluster-wide instance status and lag.",
               _combine(
                   sb.cluster_recovery_role(),
                   _aurora_guarded(
                       sb.aurora_replica_status(),
                       "aurora_replica_status() is not present on this server, so this is not an Aurora "
                       "PostgreSQL cluster. Use pg_stat_replication on the primary instead to review "
                       "replication status for this topology.",
                   ),
               ),
               "Run this first, always. If you are not on the instance you believe you are on, every later result describes the wrong machine. A writer that reports itself as a reader means a failover happened or DNS is stale -- stop the checklist and go to the failover investigation. Replica lag rising on every reader at once points at writer saturation rather than at the readers.",
               related_scripts="02_active_sessions.sql",
               table_purpose="Writer/reader role and Aurora cluster-wide replica status."),
    sql_script("02", "02_active_sessions",
               "Step 2 of 10: sizes the incident with a session and state overview across the whole instance.",
               sb.activity_overview(),
               "Compare the active count against the instance's vCPU count and against your normal baseline for this time of day. Many active sessions means work is queueing; a large idle-in-transaction population means an application is leaking transactions; a completely normal profile despite a live report is itself a finding worth stating out loud.",
               related_scripts="03_wait_events.sql",
               table_purpose="Session counts by database, state and wait-event type."),
    sql_script("03", "03_wait_events",
               "Step 3 of 10: the wait-event distribution across all backends -- the highest-signal single result in the checklist.",
               sb.wait_events_summary(),
               "Lock-dominated means blocking, and script 04 will confirm it. IO-dominated means resource or storage pressure. LWLock or IPC means internal contention from more concurrency than the instance can absorb. Few waits alongside many active sessions means genuine CPU-bound work. The PG17 pg_wait_events join means unfamiliar event names explain themselves without opening the manual.",
               related_scripts="04_blocking_locks.sql",
               table_purpose="Wait-event distribution with built-in descriptions."),
    sql_script("04", "04_blocking_locks",
               "Step 4 of 10: every blocked session, its blocking pids, and what each blocker is actually doing.",
               _combine(sb.blocked_sessions(), sb.blocking_sessions_detail()),
               "Non-empty output makes this a blocking incident first, whatever else the checklist shows -- nothing else can be fixed while the wait graph is stalled. Note how few distinct blocking pids there usually are relative to blocked sessions: that ratio is why a single action so often fixes everything. A blocker that is idle in transaction is the safest target; continue to script 05 before acting.",
               related_scripts="05_long_running_queries.sql, ../lock-storm/README.md",
               table_purpose="Blocked sessions with their blockers and what those blockers are doing."),
    sql_script("05", "05_long_running_queries",
               "Step 5 of 10: currently active queries running longer than the workload's normal profile.",
               sb.active_long_running_queries(),
               "On an exchange OLTP path, anything past a few seconds is abnormal. One unique long query alongside otherwise-normal traffic is a runaway; the same statement shape repeated across many pids is a regression or a retry storm. Capture the query text now -- it is gone the moment the session ends.",
               related_scripts="06_long_transactions.sql, ../runaway-query/README.md",
               table_purpose="Active queries above the runtime threshold, ranked by runtime."),
    sql_script("06", "06_long_transactions",
               "Step 6 of 10: transactions open longer than the threshold, whether or not they are currently executing anything.",
               sb.long_running_transactions(),
               "This is a different problem from script 05 and is frequently the quieter, more damaging one: a transaction that is idle still holds its snapshot and its locks, pinning the vacuum horizon and blocking others. Compare txn_age against the incident start -- a transaction older than the incident is a strong candidate for the trigger.",
               related_scripts="07_connection_utilization.sql, ../../concurrency-and-locking/blocked-queries/README.md",
               table_purpose="Open transactions ranked by age, active or idle."),
    sql_script("07", "07_connection_utilization",
               "Step 7 of 10: connection counts by state and current utilization against the connection ceiling.",
               _combine(sb.connections_by_state(), sb.max_connections_headroom()),
               "This tells you how much time you have. Utilization near the ceiling means the incident is about to become an availability incident regardless of its original cause, which raises the priority of everything else you have found. A state mix dominated by idle means a pool is hoarding slots; dominated by active means the database is slow and each request is holding its slot longer.",
               related_scripts="08_top_queries.sql, ../connection-exhaustion/README.md",
               table_purpose="Connections by state plus headroom against max_connections."),
    sql_script("08", "08_top_queries",
               "Step 8 of 10: top statements by cumulative execution time from pg_stat_statements.",
               _pgss_guarded(sb.pgss_top_by_total_time()),
               "Rank by total_exec_time, never by mean: a 3ms statement called two million times costs far more than a five-second report run twice. A low cache_hit_pct on a top consumer means it is driving IO as well as CPU. If the extension is absent the script prints a notice and the checklist continues -- do not stop here.",
               required_privileges=PG_MONITOR_PLUS_PGSS,
               prerequisites="pg_stat_statements installed in the current database; the script prints a notice and exits cleanly if it is not, so the checklist is never interrupted.",
               related_scripts="09_vacuum_autovacuum.sql, ../../performance/high-cpu/README.md",
               table_purpose="Top statements by cumulative execution time."),
    sql_script("09", "09_vacuum_autovacuum",
               "Step 9 of 10: running vacuum workers and the tables carrying the most dead tuples.",
               _combine(sb.autovacuum_workers_active(), sb.dead_tuples_ranked()),
               "Two findings live here. Vacuum workers on large hot tables during peak traffic are competing for the same resources as the order path. A high dead_tuple_pct with a stale last_autovacuum means vacuum cannot keep up -- and if script 06 found an old transaction, that is very likely why, because vacuum cannot clean past the oldest open snapshot.",
               related_scripts="10_storage_and_growth.sql, ../../database-health/comprehensive-health-check/README.md",
               table_purpose="Active vacuum workers plus tables ranked by dead tuples."),
    sql_script("10", "10_storage_and_growth",
               "Step 10 of 10: database sizes and the largest tables, closing the checklist with the capacity picture.",
               _combine(sb.database_sizes(), sb.largest_tables()),
               "This rarely explains a sudden incident, which is exactly why it is last -- but it catches the ones that are genuinely capacity problems, and it is the cheapest place to notice a table growing without bound before it becomes its own page. On Aurora these are logical object sizes; billed cluster-volume usage is a CloudWatch value, not a SQL one.",
               related_scripts="../../database-health/comprehensive-health-check/README.md",
               table_purpose="Database sizes and the largest tables by total size."),
]
