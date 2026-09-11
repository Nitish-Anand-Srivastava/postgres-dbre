"""Workflow definitions: concurrency-and-locking/ category (8 issue directories)."""
from __future__ import annotations

from typing import List

from . import sql_blocks as sb
from .helpers import PG_MONITOR, PG_MONITOR_PLUS_PGSS, md_script, sql_script
from .model import Workflow

CATEGORY_SLUG = "concurrency-and-locking"
CATEGORY_TITLE = "Locking and Concurrency"


def _wf(**kwargs) -> Workflow:
    kwargs.setdefault("category_slug", CATEGORY_SLUG)
    kwargs.setdefault("category_title", CATEGORY_TITLE)
    return Workflow(**kwargs)


WORKFLOWS: List[Workflow] = []

WORKFLOWS.append(_wf(
    slug="blocked-queries",
    title="Blocked Queries",
    summary="One or more sessions are waiting on a lock held by another session, delaying query completion and, if the wait chain is long, threatening a broader slowdown or timeout cascade.",
    symptoms=["Application timeouts on specific operations (order update, balance write).", "Growing count of sessions in a waiting state in pg_stat_activity.", "A single write to a hot row (account balance, order row) suddenly taking seconds instead of milliseconds."],
    business_impact=["Blocked writes on ledger/balance/order tables directly delay financial operations and can cause visible inconsistency windows to users.", "A blocking chain left unresolved can cascade into full connection pool exhaustion as more sessions queue up behind it."],
    root_causes=["A long-running transaction (application bug, forgotten COMMIT, batch job) holding a row/table lock far longer than intended.", "An idle-in-transaction session holding a lock while the client is disconnected/stuck.", "Two application code paths taking locks on the same rows in different orders (a precursor to a deadlock, not yet detected as one).", "A DDL statement (schema-changes) waiting for/holding an AccessExclusiveLock against ongoing traffic."],
    investigation_strategy=["Identify every currently blocked session and its wait duration.", "Identify the specific session(s) directly blocking each of them.", "Inspect what the blocking session is doing/has done and how long its transaction has been open.", "Decide whether to wait, escalate to the owning team, or (rarely) terminate the blocking session."],
    prerequisites=["pg_monitor role membership.", "Awareness of change-freeze/incident policy before terminating any backend."],
    interpretation_guide=["A blocking session that is `idle in transaction` with no active query is the clearest case for safe intervention (it is not doing useful work).", "A blocking session that is `active` and genuinely executing a long legitimate operation requires coordination with its owner before any termination.", "Multiple blocked sessions behind a single blocker is high leverage: fixing the one blocker unblocks everyone downstream."],
    remediation_immediate=["If the blocker is idle-in-transaction and confirmed abandoned/orphaned, terminate it with `SELECT pg_terminate_backend(<pid>);` only after documented approval -- this rolls back its transaction.", "If the blocker is a legitimate long operation, coordinate with its owner to let it finish or cancel it gracefully."],
    remediation_short_term=["Add `idle_in_transaction_session_timeout` at the role/database level to prevent recurrence.", "Add `lock_timeout` to latency-sensitive application roles so a blocked session fails fast and retries instead of queuing indefinitely."],
    remediation_long_term=["Review application transaction boundaries to ensure locks are held for the minimum necessary duration.", "Introduce row-level locking discipline documentation for hot tables (see the crypto-exchange hot-row-contention guidance in the root README)."],
    production_safety=["Investigation scripts are read-only.", "`pg_terminate_backend()` rolls back the target transaction -- never run it against a session performing a financial write without confirming rollback is safe and idempotent from the application's perspective."],
    escalation_criteria=["The blocking session belongs to a system/replication process rather than application code -- escalate to database engineering before terminating anything.", "The blocking chain does not resolve after the identified blocker is handled (a second, hidden blocker exists) -- escalate for a deeper investigation."],
    related_issues=["../lock-contention/README.md", "../deadlocks/README.md", "../idle-in-transaction/README.md", "../../incident-response/lock-storm/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_identify_blocked_sessions", "Identifies every session currently blocked, with its blocking pid(s), using the built-in pg_blocking_pids() helper.",
               sb.blocked_sessions(),
               "Sort by blocked_duration. Sessions blocked for more than a few seconds on an OLTP path are actionable; note the blocking_pids for the next script.",
               related_scripts="02_identify_blocking_sessions.sql"),
    sql_script("02", "02_identify_blocking_sessions", "Expands each blocking relationship to show what the blocking session is doing and for how long.",
               sb.blocking_sessions_detail(),
               "A blocking_state of 'idle in transaction' with a large blocking_txn_age is the highest-priority, safest-to-resolve finding. An 'active' blocker running a legitimate long query needs owner coordination instead.",
               related_scripts="01_identify_blocked_sessions.sql, 03_lock_detail.sql"),
    sql_script("03", "03_lock_detail", "Shows the raw lock detail (mode, object, granted state) behind the blocking relationship for precise diagnosis.",
               sb.lock_detail_by_mode(),
               "Match the relation_name against the application's known hot tables (orders, balances) to understand exactly what resource is contended.",
               related_scripts="04_long_running_transactions.sql"),
    sql_script("04", "04_long_running_transactions", "Confirms whether the blocking session is also one of the oldest open transactions on the instance.",
               sb.long_running_transactions(),
               "If the blocker also appears here with a large txn_age, resolving it has the dual benefit of unblocking sessions AND reducing vacuum-relevant transaction age.",
               related_scripts="../long-running-transactions/README.md"),
]

WORKFLOWS.append(_wf(
    slug="lock-contention",
    title="Lock Contention",
    summary="Broader, sustained lock contention across the workload (not just one isolated blocked session) -- many sessions repeatedly waiting on locks, degrading overall throughput and latency.",
    symptoms=["Elevated Lock wait_event_type share in overall session load.", "Throughput degradation correlated with lock waits rather than CPU/IO.", "Recurring, short-lived blocking episodes rather than one single long block."],
    business_impact=["Sustained contention on hot rows (a popular trading pair's order book, a shared counter/sequence) caps the effective throughput of the entire feature regardless of available CPU/IO capacity."],
    root_causes=["Hot-row contention: many transactions updating the same small set of rows (a single market's order book summary row, a global sequence/counter table).", "Overly broad locking: a query or ORM taking a table-level lock where a row-level lock would suffice.", "Long transactions holding locks incidentally needed by many other short transactions.", "Missing indexes causing UPDATE/DELETE to lock more rows than necessary via a sequential scan under `SELECT ... FOR UPDATE`."],
    investigation_strategy=["Quantify the current scale of lock waiting across the whole instance, not just one session.", "Identify which relations/rows are the most contended.", "Check whether contention correlates with a small number of long-held locks or many short-lived ones.", "Check for missing indexes on the contended table(s) that could be widening lock scope."],
    prerequisites=["pg_monitor role membership.", "log_lock_waits enabled (via parameter group) recommended so contention is also visible in PostgreSQL logs/CloudWatch Logs, not just point-in-time snapshots."],
    interpretation_guide=["A small number of relations accounting for most contention narrows the fix to specific hot tables rather than a systemic issue.", "If contention is spread evenly across many unrelated tables, suspect a systemic cause (e.g. an ORM defaulting to SERIALIZABLE isolation, or missing indexes across the board) rather than one hot table."],
    remediation_immediate=["Identify and resolve any single long-held blocking transaction contributing disproportionately (see blocked-queries)."],
    remediation_short_term=["Add missing indexes so row-locking operations (`UPDATE`/`SELECT FOR UPDATE`) only lock the intended rows.", "Reduce transaction scope so locks are held for the minimum necessary time.", "Consider `SELECT ... FOR UPDATE SKIP LOCKED` for queue-like workloads where contention is expected and acceptable to skip rather than wait."],
    remediation_long_term=["Redesign hot-row patterns (e.g. sharding a global counter, using an append-only ledger with periodic aggregation instead of updating one row per transaction).", "Introduce application-level backoff/retry with jitter for expected contention hot spots."],
    production_safety=["All investigation scripts are read-only.", "Do not blindly add `NOWAIT`/`SKIP LOCKED` to existing queries without confirming the business logic can tolerate skipping a locked row."],
    escalation_criteria=["Contention is traced to a fundamental data-model hot spot (e.g. one row representing a single trading pair's global state) -- this typically requires an application/schema redesign decision, escalate to database engineering and application architecture leadership."],
    related_issues=["../blocked-queries/README.md", "../transaction-contention/README.md", "../../tables-and-indexes/missing-index-candidates/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_contention_scale_overview", "Quantifies current lock-wait load across the instance as a starting scope check.",
               sb.connection_contention_by_wait_event(),
               "A large backend_count for wait_event_type = 'Lock' relative to total connections indicates broad contention, not an isolated incident.",
               related_scripts="02_most_contended_relations.sql"),
    sql_script("02", "02_most_contended_relations", "Identifies which specific relations/locks currently have the most waiters.",
               sb.lock_detail_by_mode(),
               "Group mentally by relation_name; a small number of tables accounting for most waiting rows are your highest-priority fix targets.",
               related_scripts="03_ddl_style_locks.sql"),
    sql_script("03", "03_ddl_style_locks", "Checks specifically for stronger lock modes (ShareUpdateExclusive/ShareRowExclusive/AccessExclusive) contributing to contention.",
               sb.ddl_lock_waits(),
               "Repeated appearances of these stronger modes during normal operations (not a deliberate maintenance window) suggest an unexpected DDL-like operation (e.g. an ORM auto-migration) is running against production.",
               related_scripts="../ddl-blocking/README.md"),
    sql_script("04", "04_missing_indexes_on_contended_tables", "Checks index coverage on the most contended tables identified in script 02, since a missing index can widen lock scope under row-locking operations.",
               sb.foreign_keys_missing_index(),
               "A contended table with an unindexed foreign key or filter column is very likely locking far more rows/pages than the business logic actually requires.",
               related_scripts="../../tables-and-indexes/missing-index-candidates/README.md"),
]

WORKFLOWS.append(_wf(
    slug="deadlocks",
    title="Deadlocks",
    summary="Two or more transactions are (or recently were) mutually waiting on locks held by each other, causing PostgreSQL's deadlock detector to abort one of them automatically.",
    symptoms=["Application-level errors: 'deadlock detected' (SQLSTATE 40P01).", "A rising `deadlocks` counter in pg_stat_database.", "Intermittent transaction failures under concurrent load that succeed on retry."],
    business_impact=["Deadlocked transactions are aborted automatically by PostgreSQL -- if the application does not retry correctly, this can silently drop a user-facing write (an order update, a balance change) that appeared to fail from the user's perspective."],
    root_causes=["Two code paths acquiring locks on the same set of rows/tables in a different order under concurrent execution.", "A single statement that internally touches multiple tables/rows in a non-deterministic order (e.g. a multi-row UPDATE without an explicit ORDER BY where deadlock risk exists across concurrent callers).", "Foreign-key-driven locking: an UPDATE/DELETE on a parent row taking a lock that conflicts with a concurrent child-table write's FK check."],
    investigation_strategy=["Confirm deadlocks are occurring and quantify frequency via pg_stat_database counters.", "Retrieve the actual deadlock details from the PostgreSQL log (CloudWatch Logs on Aurora) since pg_locks/pg_stat_activity do not retain historical deadlock detail once resolved.", "Identify the specific transactions/queries involved from the log entries.", "Determine the lock-acquisition order difference between the two code paths."],
    prerequisites=["`log_lock_waits` and default deadlock logging enabled (on by default) with logs exported to CloudWatch Logs for the Aurora instance -- this workflow's most important evidence lives in the log, not in live catalogs.", "pg_monitor role membership for the counter check."],
    interpretation_guide=["The PostgreSQL deadlock log entry lists both processes, the queries they were running, and the exact lock types/objects involved -- this is the ground truth for root-causing which two code paths are in conflict, not a live SQL query (the deadlock is already resolved by the time you look).", "A steadily rising deadlocks counter with no corresponding application error-rate increase suggests the application is already retrying transparently -- lower urgency, but still worth fixing at the root."],
    remediation_immediate=["Confirm the application is retrying deadlock-aborted transactions (SQLSTATE 40P01) correctly; if not, this is an urgent application-level bug fix, not a database fix."],
    remediation_short_term=["Standardize lock-acquisition order across all code paths touching the same tables (e.g. always lock accounts in ascending id order).", "Add explicit `ORDER BY` to multi-row UPDATE/DELETE statements that touch more than one row to make acquisition order deterministic."],
    remediation_long_term=["Introduce application-level architectural patterns (single-writer-per-aggregate, optimistic concurrency with version columns) that eliminate the possibility of circular waits for hot financial entities."],
    production_safety=["All investigation scripts here are read-only.", "PostgreSQL's deadlock detector already resolves deadlocks automatically by aborting one transaction -- no manual DBA intervention is possible or necessary at the moment a deadlock occurs."],
    escalation_criteria=["Deadlock rate increases sharply after a deployment -- escalate to the deploying team with the log evidence immediately.", "Deadlocks involve core ledger/balance tables -- escalate to database engineering leadership given the financial-integrity sensitivity even if the application retry logic is confirmed correct."],
    related_issues=["../lock-contention/README.md", "../transaction-contention/README.md"],
    aurora_notes=["PostgreSQL's deadlock log messages are written to the standard PostgreSQL log, which on Aurora is exported to CloudWatch Logs (log group `/aws/rds/cluster/<cluster-id>/postgresql`) rather than a local filesystem -- use CloudWatch Logs Insights to search for 'deadlock detected' across the fleet."],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_deadlock_counters", "Confirms deadlocks are occurring and quantifies frequency per database since the last stats reset.",
               sb.deadlock_counters_by_database(),
               "A non-zero and/or rising deadlocks count confirms the symptom; note stats_reset to know the counting window, and correlate the rate against recent traffic/deploy changes.",
               related_scripts="02_current_lock_graph.sql"),
    sql_script("02", "02_current_lock_graph", "Captures the current lock graph, in case a near-deadlock (a long circular wait about to be detected) is actively forming.",
               sb.lock_detail_by_mode(),
               "This will NOT show a deadlock that has already been detected and resolved (PostgreSQL aborts one side automatically within deadlock_timeout) -- its value is catching an in-progress circular wait before the detector fires, or confirming general contention shape.",
               related_scripts="03_transaction_age_of_contended_sessions.sql"),
    sql_script("03", "03_transaction_age_of_contended_sessions", "Checks transaction age for currently active/blocked sessions, to identify which transactions have been open long enough to plausibly be involved in repeated deadlock cycles.",
               sb.long_running_transactions(),
               "Cross-reference pids/query text here against the CloudWatch Logs deadlock entries (see this workflow's Aurora note) to connect live session context with historical deadlock evidence.",
               related_scripts="../../observability/cloudwatch/README.md"),
]

WORKFLOWS.append(_wf(
    slug="long-running-transactions",
    title="Long-Running Transactions",
    summary="A transaction has been open significantly longer than the workload's normal transaction duration, risking lock retention, vacuum horizon stalls, and increased rollback cost if it eventually fails.",
    symptoms=["A session's xact_start age far exceeds typical OLTP transaction duration (seconds, not minutes/hours).", "Autovacuum unable to advance relfrozenxid/clean up dead tuples on tables touched by the long transaction.", "Growing table bloat correlated with the transaction's start time."],
    business_impact=["Long transactions on ledger/order tables hold locks and prevent vacuum cleanup, degrading performance for every other session touching the same tables for as long as the transaction remains open."],
    root_causes=["A batch/reporting job wrapped in a single large transaction instead of batched smaller ones.", "An application bug: a transaction opened and never committed/rolled back (often paired with idle-in-transaction).", "A long-running analytical query executed directly against the OLTP database inside an explicit transaction.", "A stuck two-phase-commit (prepared transaction) left unresolved."],
    investigation_strategy=["List all transactions currently open beyond a reasonable threshold, ranked by age.", "For each, determine if it is actively executing a query or idle.", "Check for any associated locks the transaction is holding that could be impacting others.", "Check whether the transaction's age is materially affecting database-wide XID age / vacuum progress."],
    prerequisites=["pg_monitor role membership."],
    interpretation_guide=["Age alone does not make a transaction a problem -- a multi-minute batch job may be legitimate. The key questions are: (1) is it holding locks that block others, and (2) is its age approaching a meaningful fraction of autovacuum_freeze_max_age for the busiest tables it touches."],
    remediation_immediate=["If confirmed abandoned/orphaned and holding blocking locks, terminate per the safety guidance in blocked-queries.", "If it is a legitimate long batch job, ensure it is not scheduled to overlap with peak trading hours going forward."],
    remediation_short_term=["Break large batch operations into smaller, committed-in-chunks transactions.", "Set `idle_in_transaction_session_timeout` and a reasonable `statement_timeout` for application roles."],
    remediation_long_term=["Route long-running analytical/reporting queries to a reader endpoint or a dedicated analytical replica instead of the writer.", "Add monitoring/alerting on transaction age directly (not just query duration) so this is caught proactively."],
    production_safety=["Investigation scripts are read-only.", "Terminating a long-running transaction rolls back all of its uncommitted work -- confirm this is safe before doing so."],
    escalation_criteria=["Transaction age approaches a meaningful percentage of autovacuum_freeze_max_age on any table it touches -- escalate immediately per transactions-and-xid/xid-wraparound-risk."],
    related_issues=["../idle-in-transaction/README.md", "../blocked-queries/README.md", "../../transactions-and-xid/xid-wraparound-risk/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_open_transactions_by_age", "Lists all currently open transactions ranked by age, regardless of whether they are actively running a query.",
               sb.long_running_transactions(),
               "Focus on txn_age, not query runtime -- a session can show a short-running current query while its overarching transaction has been open for a long time.",
               related_scripts="02_locks_held_by_long_transactions.sql"),
    sql_script("02", "02_locks_held_by_long_transactions", "Shows what locks the oldest open transactions are currently holding.",
               sb.lock_detail_by_mode(),
               "A long transaction holding no meaningful locks is lower priority than one holding a lock that others are actively waiting on.",
               related_scripts="03_xid_age_impact.sql"),
    sql_script("03", "03_xid_age_impact", "Checks database-level transaction age to assess whether the long-running transaction is meaningfully delaying vacuum's ability to advance the freeze horizon.",
               sb.database_transaction_age(),
               "If pct_of_freeze_max_age is climbing while a specific long transaction remains open, resolving that transaction is now a wraparound-prevention action, not just a performance one.",
               related_scripts="../../transactions-and-xid/xid-wraparound-risk/README.md"),
]

WORKFLOWS.append(_wf(
    slug="idle-in-transaction",
    title="Idle-in-Transaction Sessions",
    summary="Sessions holding an open transaction while sitting idle (not executing any statement) -- a specific and very common form of long-running-transaction typically caused by an application/connection-pool bug rather than a legitimate long operation.",
    symptoms=["Sessions with `state = 'idle in transaction'` accumulating and persisting across snapshots.", "Autovacuum unable to make progress cleaning up dead tuples.", "Growing table bloat with no corresponding growth in legitimate long-running query activity."],
    business_impact=["Idle-in-transaction sessions serve no business purpose while active, yet consume a connection slot and hold locks/snapshots exactly as if they were doing useful work -- pure operational risk with zero benefit."],
    root_causes=["Application code that opens a transaction, then makes a network call (to another service, cache, or the user) before committing, and that call hangs or is never completed.", "A connection returned to a pool without an explicit COMMIT/ROLLBACK after an exception.", "An interactive psql/GUI session left open by an engineer mid-transaction."],
    investigation_strategy=["List all idle-in-transaction sessions ranked by duration.", "Identify the application_name/usename to attribute each to an owning service.", "Check whether any are holding locks currently blocking other sessions.", "Confirm whether `idle_in_transaction_session_timeout` is configured, and at what value."],
    prerequisites=["pg_monitor role membership."],
    interpretation_guide=["Any idle-in-transaction session older than a few seconds on a low-latency OLTP path is abnormal and should be investigated; this is different from long-running-transactions where an actively executing long operation may be legitimate."],
    remediation_immediate=["Terminate confirmed-orphaned idle-in-transaction sessions per the safety guidance in blocked-queries, prioritizing any holding blocking locks."],
    remediation_short_term=["Set `idle_in_transaction_session_timeout` at the role or database level so these are auto-terminated by PostgreSQL itself going forward.", "Audit the owning application's transaction-boundary handling (ensure try/finally or equivalent always closes the transaction)."],
    remediation_long_term=["Add APM instrumentation/alerting on transaction duration at the application layer to catch this class of bug before it reaches the database as a symptom."],
    production_safety=["Investigation scripts are read-only.", "Terminating an idle-in-transaction session always rolls back its (by definition, currently paused) transaction -- this is virtually always safe since no statement is in flight, but confirm no unusual application semantics rely on a long-held open transaction."],
    escalation_criteria=["A specific application/service is repeatedly identified as the source -- escalate to that team with the evidence; this is an application bug fix, not an ongoing DBA task."],
    related_issues=["../long-running-transactions/README.md", "../blocked-queries/README.md", "../../connections/idle-in-transaction/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_idle_in_transaction_sessions", "Lists all sessions currently idle in an open transaction, ranked by duration.",
               sb.idle_in_transaction_sessions(),
               "Any result older than single-digit seconds on a low-latency OLTP path warrants investigation; group by application_name to find the owning service.",
               related_scripts="02_locks_held.sql"),
    sql_script("02", "02_locks_held", "Checks whether any idle-in-transaction session is currently holding a lock that is blocking others.",
               sb.blocking_sessions_detail(),
               "An idle-in-transaction session appearing as a blocking_pid here is the highest-priority remediation target -- it is causing active harm while doing zero useful work.",
               related_scripts="../blocked-queries/README.md"),
    sql_script("03", "03_idle_in_transaction_timeout_setting", "Confirms whether idle_in_transaction_session_timeout is configured, to assess whether this class of issue will self-resolve.",
               sb.key_settings_snapshot(),
               "A setting of 0 (disabled) means idle-in-transaction sessions can persist indefinitely; consider setting a role/database-level timeout as a durable fix.",
               related_scripts="../../connections/idle-in-transaction/README.md"),
]

WORKFLOWS.append(_wf(
    slug="transaction-contention",
    title="Transaction Contention",
    summary="A broader pattern of concurrent transactions repeatedly conflicting with each other -- not necessarily deadlocking or fully blocking, but serializing, retrying, or aborting (serialization failures under REPEATABLE READ/SERIALIZABLE) at a rate that measurably reduces throughput.",
    symptoms=["Rising serialization_failure (SQLSTATE 40001) errors at the application layer.", "Throughput lower than expected despite adequate CPU/IO/connection headroom.", "Application-level retry counters increasing for specific transaction types."],
    business_impact=["Serialization failures on financial transactions (e.g. a balance check-then-update pattern) that are not retried correctly can silently drop a legitimate operation."],
    root_causes=["Use of SERIALIZABLE or REPEATABLE READ isolation for hot-row workloads without corresponding retry logic.", "A check-then-act pattern (SELECT balance, then UPDATE) racing across concurrent requests for the same account without row-level locking (`SELECT ... FOR UPDATE`).", "Excessive concurrency targeting the same narrow set of rows (see the hot-row-contention guidance in the root README)."],
    investigation_strategy=["Confirm the isolation levels in use for the affected transaction type.", "Check current lock wait patterns on the specific rows/tables involved.", "Check pg_stat_database for rollback rate as a proxy for contention-driven aborts.", "Review whether the application uses explicit row locking (`FOR UPDATE`) or optimistic concurrency (version column) for the affected pattern."],
    prerequisites=["pg_monitor role membership.", "Access to the application's transaction isolation-level configuration."],
    interpretation_guide=["A high xact_rollback rate concentrated in a specific time window/workload, combined with confirmed non-default isolation levels, points directly at serialization-failure-driven contention rather than a business-logic bug."],
    remediation_immediate=["If a specific operation is failing at a high rate, confirm the application is retrying serialization failures with backoff; if not, this is an urgent application fix."],
    remediation_short_term=["Switch the affected pattern to explicit `SELECT ... FOR UPDATE` with READ COMMITTED isolation if strict serializability is not actually required, since READ COMMITTED with row locks avoids most serialization failures for simple check-then-act patterns.", "Add `SET LOCAL lock_timeout` so contending transactions fail fast and retry rather than queue."],
    remediation_long_term=["Redesign hot financial-entity update patterns to use optimistic concurrency (version/updated_at column with a conditional UPDATE) or an append-only ledger with periodic aggregation instead of repeated in-place updates."],
    production_safety=["Investigation scripts are read-only.", "Isolation-level changes must be tested thoroughly against the specific business invariants they protect before rollout."],
    escalation_criteria=["The contended pattern is a core financial invariant (balance, position) and a fix requires an application/data-model change -- escalate to database engineering and the owning application team jointly."],
    related_issues=["../lock-contention/README.md", "../deadlocks/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_rollback_rate_by_database", "Checks the transaction rollback rate per database as a proxy for contention-driven aborts (including serialization failures).",
               sb.deadlock_counters_by_database(),
               "A high or rising rollback_pct alongside otherwise-normal query performance suggests contention-driven aborts/retries rather than raw slow queries.",
               related_scripts="02_current_isolation_levels.sql"),
    sql_script("02", "02_current_isolation_levels", "Shows the transaction isolation level in use by each currently active session.",
               """
-- Current transaction isolation level per active backend. Non-default
-- levels (repeatable read, serializable) are far more prone to serialization
-- failures under concurrent hot-row access than read committed.
SELECT
    a.pid,
    a.usename,
    a.application_name,
    s.setting                                                   AS session_default_isolation,
    a.state,
    left(a.query, 160)                                           AS current_query
FROM pg_stat_activity a
CROSS JOIN LATERAL (
    SELECT setting FROM pg_settings WHERE name = 'transaction_isolation'
) s
WHERE a.pid <> pg_backend_pid()
  AND a.state <> 'idle'
ORDER BY a.application_name;
""".strip("\n"),
               "This shows the session/database default, not necessarily what a specific transaction explicitly requested via `SET TRANSACTION ISOLATION LEVEL`; combine with an application-code review to confirm the actual isolation level used for the contended pattern.",
               related_scripts="03_contended_rows.sql"),
    sql_script("03", "03_contended_rows", "Identifies the specific rows/relations currently experiencing the most lock waiting.",
               sb.lock_detail_by_mode(),
               "Repeated appearances of the same relation across multiple snapshots over time confirms a genuine hot-row pattern rather than a one-off spike.",
               related_scripts="../../database-health/comprehensive-health-check/README.md"),
]

WORKFLOWS.append(_wf(
    slug="ddl-blocking",
    title="DDL Blocking Application Traffic",
    summary="A DDL statement (ALTER TABLE, CREATE INDEX without CONCURRENTLY, VACUUM FULL, TRUNCATE) is holding or waiting for a strong lock (e.g. AccessExclusiveLock) that blocks a wide swath of normal application queries -- the classic 'one migration takes down the app' incident.",
    symptoms=["A sudden, near-total stall of queries against one specific table.", "A migration/deployment step correlates with the stall's onset.", "Many sessions blocked simultaneously on the same relation."],
    business_impact=["DDL-driven stalls typically block ALL access (reads and writes) to the affected table, unlike a typical row-level contention issue -- this is often the most severe form of concurrency incident."],
    root_causes=["A non-concurrent index build/rebuild on a live production table.", "An ALTER TABLE that requires a full table rewrite (adding a column with a volatile default pre-PG11 semantics, changing a column type) taking AccessExclusiveLock for the duration.", "The DDL statement itself is queued behind a long-running transaction, and every subsequent query queues up behind the DDL's own lock request (DDL doesn't need to be running long to cause this -- it just needs to be waiting)."],
    investigation_strategy=["Identify the DDL statement itself: is it running, or is it waiting for a lock?", "If waiting, identify what it is waiting on (typically an old long-running transaction).", "Quantify how many sessions are now queued behind the DDL.", "Decide: wait for the blocker to finish, cancel the DDL, or (in the worst case) terminate the underlying blocker."],
    prerequisites=["pg_monitor role membership.", "Direct communication channel with whoever initiated the DDL/deployment."],
    interpretation_guide=["Because lock requests queue strictly in arrival order, a DDL statement waiting for a lock will itself block all subsequent queries against that table, even queries that would not conflict with each other -- this is why a single blocked ALTER TABLE can look like a full table outage."],
    remediation_immediate=["Cancel the DDL statement itself (`SELECT pg_cancel_backend(<ddl_pid>);`) to immediately drain the queue if the DDL cannot be allowed to keep waiting -- this is generally safer than terminating the underlying long-running blocker.", "If cancelling the DDL is not acceptable, resolve the underlying blocking transaction per blocked-queries."],
    remediation_short_term=["Always use `CREATE INDEX CONCURRENTLY` / `DROP INDEX CONCURRENTLY` / `ALTER TABLE ... ADD CONSTRAINT ... NOT VALID` + `VALIDATE CONSTRAINT` patterns for production DDL (see schema-changes/).", "Set a conservative `lock_timeout` for the session running planned DDL so it fails fast instead of queuing indefinitely and blocking others."],
    remediation_long_term=["Adopt a mandatory pre-deployment DDL lock-risk review (see schema-changes/ddl-lock-investigation) for every migration touching a hot table."],
    production_safety=["Cancelling a DDL statement is safe (it rolls back cleanly, no data change was committed); always prefer cancelling the DDL over terminating an unrelated long-running application transaction unless the DDL is time-critical."],
    escalation_criteria=["The DDL is part of an in-progress deployment and cannot be simply cancelled without breaking application compatibility -- escalate to the deploying team immediately to decide between waiting, cancelling, or rolling back the deployment."],
    related_issues=["../blocked-queries/README.md", "../../schema-changes/ddl-lock-investigation/README.md", "../../schema-changes/safe-index-creation/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_ddl_style_lock_waits", "Identifies sessions holding or waiting for strong (DDL-style) lock modes and whether the DDL itself is granted or queued.",
               sb.ddl_lock_waits(),
               "A DDL statement with granted = false means it is the one waiting, not the one blocking -- everyone else is queued behind IT, waiting for its lock request to clear the queue ahead of them.",
               related_scripts="02_who_is_queued_behind_ddl.sql"),
    sql_script("02", "02_who_is_queued_behind_ddl", "Shows every other session now queued behind the DDL statement's own lock request.",
               sb.blocked_sessions(),
               "The count and diversity of blocked_pid entries here quantifies the blast radius of the DDL-driven stall -- use this to communicate incident severity accurately.",
               related_scripts="03_root_blocker_of_ddl.sql"),
    sql_script("03", "03_root_blocker_of_ddl", "Identifies the original long-running transaction that the DDL statement itself is waiting on.",
               sb.blocking_sessions_detail(),
               "This is the true root cause -- an old transaction that existed before the DDL was even issued. Resolving it (or cancelling the DDL instead) are your two options.",
               related_scripts="../../schema-changes/ddl-lock-investigation/README.md"),
]

WORKFLOWS.append(_wf(
    slug="connection-contention",
    title="Connection-Level Contention",
    summary="Sessions are waiting not on table/row locks but on connection-level or client-level resources -- for example, waiting for a connection pool slot, or waiting on Client wait events indicating the server is ready but the client/network side is slow to proceed.",
    symptoms=["High Client or IPC wait_event_type share in current load.", "Application-side connection pool exhaustion errors even though the database's own max_connections has headroom.", "Sessions sitting in 'active' state for long periods with wait_event = 'ClientRead' (server waiting for the client to send the next command)."],
    business_impact=["Connection-level contention often indicates the bottleneck is actually in the application/pooler layer, not the database -- misdiagnosing it as a database problem wastes response time and can lead to ineffective database-side remediation."],
    root_causes=["Application connection pool sized far below actual concurrency needs, causing queuing before a connection even reaches the database.", "A pooler (PgBouncer) in session mode holding connections open across idle periods far longer than necessary, starving the pool.", "Network latency/instability between application and database causing sessions to sit in ClientRead longer than expected.", "An application holding a connection open while performing a slow non-database operation (an external API call) mid-transaction."],
    investigation_strategy=["Break down current wait events specifically for Client/IPC types.", "Check overall connection count and utilization against max_connections.", "Check connection distribution across application_name/pooler identities to spot an undersized or misconfigured pool.", "Cross-reference with idle-in-transaction findings, since a slow external call mid-transaction produces both symptoms simultaneously."],
    prerequisites=["pg_monitor role membership.", "Visibility into the application/pooler-side connection pool configuration and metrics."],
    interpretation_guide=["A high share of ClientRead wait events is normal for many idle connections but abnormal for sessions that should be actively executing a tight request/response loop -- the distinguishing factor is whether the session is inside an open transaction while waiting (see idle-in-transaction) or genuinely between independent statements."],
    remediation_immediate=["If a pooler is clearly undersized, temporarily increase its pool size within the database's max_connections headroom."],
    remediation_short_term=["Right-size the connection pool based on observed concurrency, not a guess -- use max_connections_headroom findings alongside application-side pool metrics.", "Move PgBouncer (or equivalent) to transaction pooling mode if currently in session mode and the application does not require session-level state, to dramatically improve connection reuse efficiency."],
    remediation_long_term=["Establish connection budget documentation per service so pool sizing is a deliberate capacity decision, not ad hoc (see connections/max-connections-planning)."],
    production_safety=["All investigation scripts are read-only."],
    escalation_criteria=["Root cause is clearly network/application-side -- hand off to SRE/application teams with the gathered evidence rather than continuing database-side tuning."],
    related_issues=["../../connections/connection-pooling/README.md", "../../connections/connection-exhaustion/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_client_and_ipc_wait_breakdown", "Breaks down current wait events specifically for Client and IPC types to isolate connection-level (as opposed to lock/IO) contention.",
               sb.connection_contention_by_wait_event(),
               "A large ClientRead count on sessions inside an open transaction (cross-check against idle-in-transaction) suggests the client, not the database, is the bottleneck.",
               related_scripts="02_connection_headroom.sql"),
    sql_script("02", "02_connection_headroom", "Checks whether the database's own max_connections is the limiting factor, or whether it has headroom (pointing at an application/pooler-side limit instead).",
               sb.max_connections_headroom(),
               "Significant headroom here combined with application-reported pool exhaustion confirms the bottleneck is the application/pooler configuration, not the database.",
               related_scripts="03_connections_by_pool_identity.sql"),
    sql_script("03", "03_connections_by_pool_identity", "Breaks connections down by application_name/usename to identify which pool/service is consuming the most connection slots.",
               sb.connections_by_application_and_user(),
               "An application_name with a disproportionate idle_count relative to its active_count suggests the pool is holding connections open far longer than needed (a session-mode pooler symptom).",
               related_scripts="../../connections/connection-pooling/README.md"),
]
