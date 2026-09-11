# Production Triage -- Rapid Response Checklist

**Category:** Incident Response | **Workflow:** `incident-response/production-triage`

## 1. Problem Description

The single checklist to run, start to finish, during ANY production incident on this cluster before deciding what to do next. Ten read-only scripts, in a fixed order, that take a complete picture of the database in a few minutes: cluster role, session load, wait events, blocking, long queries, long transactions, connection headroom, top statements, vacuum state, and storage. Every other workflow in this category answers a specific question; this one tells you which question to ask, and leaves behind the snapshot that the post-incident review will need.

## 2. Typical Symptoms

- Any page against this database cluster, from any source, with any symptom.
- A vague or multi-symptom report ('things feel slow', 'some errors', 'the dashboard looks wrong') that does not map cleanly to one workflow yet.
- Several teams reporting different symptoms at once, which usually means one shared cause rather than several independent problems.
- A handover to a second responder who needs the full current state of the database in one pass rather than a narrative.

## 3. Business Impact

- Triage speed is the largest controllable factor in the duration of an exchange incident: the database is the shared dependency of order entry, wallets, the ledger and settlement, so every minute of misdirected investigation is a minute of customer impact across all of them.
- Acting on a guess -- terminating sessions, failing over, restarting a pooler -- without this snapshot routinely adds a second, self-inflicted incident on top of the first.
- The snapshot this checklist produces is the only evidence the post-incident review will have: pg_stat_activity retains nothing once sessions end, and lock waits vanish the moment they clear.

## 4. Possible Root Causes

- Not applicable as a cause category -- this workflow is the diagnostic entry point. Its output identifies which specific workflow owns the root cause.
- In practice the checklist resolves to one of: blocking or lock contention, resource saturation, connection exhaustion, a runaway or regressed query, replication or failover, or a cause outside the database entirely.

## 5. Investigation Strategy

1. Run all ten scripts in numeric order, start to finish, before deciding anything. The order is deliberate: it goes from cluster-wide facts to progressively narrower detail, so each script is interpreted in the context the previous one established.
2. Do not skip ahead because a symptom 'obviously' matches a workflow. The most expensive incidents in an exchange are the ones where the obvious explanation was a symptom of something else, and skipping the checklist is how that happens.
3. Do not stop early when you find something interesting. Finish all ten: compound incidents (a lock storm that has caused connection exhaustion, a slow query that has delayed vacuum) are common, and the second finding changes the order of the fixes.
4. Capture the output of every script into the incident channel or a file as you go. This is your forensic record, and most of it is unreproducible ten minutes later.
5. Route on the evidence: Lock-dominated waits and blocking go to lock-storm; connection utilization at the ceiling goes to connection-exhaustion; one dominant statement goes to runaway-query; a cluster-role surprise goes to failover investigation; broad latency with no single cause goes to sudden-latency-spike.
6. Only after all ten scripts, choose the specific workflow, and take the first action from that workflow's guarded runbook -- not from this one, which deliberately contains no remediation at all.

## 6. Prerequisites

- `pg_monitor` (or `pg_read_all_stats`) role membership, and CONNECT on the target database. Nothing more: this checklist is deliberately the lowest-privilege, lowest-prerequisite entry point in the entire toolkit.
- `pg_stat_statements` for script 08 only; it prints a notice and continues cleanly if the extension is absent, so a missing extension never stops the checklist.
- A connection to the instance you are investigating -- ideally the writer, since several scripts describe instance-local state that differs between writer and readers.
- Somewhere to paste the output: an incident channel, a scratch file, or a transcript. Do not rely on scrollback.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_cluster_database_status.sql`](scripts/01_cluster_database_status.sql) -- Step 1 of 10: confirms whether this connection is on the writer or a reader, and reports Aurora's cluster-wide instance status and lag.
2. [`scripts/02_active_sessions.sql`](scripts/02_active_sessions.sql) -- Step 2 of 10: sizes the incident with a session and state overview across the whole instance.
3. [`scripts/03_wait_events.sql`](scripts/03_wait_events.sql) -- Step 3 of 10: the wait-event distribution across all backends -- the highest-signal single result in the checklist.
4. [`scripts/04_blocking_locks.sql`](scripts/04_blocking_locks.sql) -- Step 4 of 10: every blocked session, its blocking pids, and what each blocker is actually doing.
5. [`scripts/05_long_running_queries.sql`](scripts/05_long_running_queries.sql) -- Step 5 of 10: currently active queries running longer than the workload's normal profile.
6. [`scripts/06_long_transactions.sql`](scripts/06_long_transactions.sql) -- Step 6 of 10: transactions open longer than the threshold, whether or not they are currently executing anything.
7. [`scripts/07_connection_utilization.sql`](scripts/07_connection_utilization.sql) -- Step 7 of 10: connection counts by state and current utilization against the connection ceiling.
8. [`scripts/08_top_queries.sql`](scripts/08_top_queries.sql) -- Step 8 of 10: top statements by cumulative execution time from pg_stat_statements.
9. [`scripts/09_vacuum_autovacuum.sql`](scripts/09_vacuum_autovacuum.sql) -- Step 9 of 10: running vacuum workers and the tables carrying the most dead tuples.
10. [`scripts/10_storage_and_growth.sql`](scripts/10_storage_and_growth.sql) -- Step 10 of 10: database sizes and the largest tables, closing the checklist with the capacity picture.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Script 01 is Aurora-aware and matters more here than on community PostgreSQL: every Aurora reader reports pg_is_in_recovery() = true permanently, and the writer endpoint is a DNS record that moves during failover, so confirming which instance answered is a genuine finding rather than a formality.
- Several of these views are instance-local (sessions, locks, waits, IO), so running the checklist on a reader describes that reader only. During a cluster-wide incident, run it on the writer first, then on the affected reader.
- The database has no visibility into instance CPU, storage IOPS or network throughput -- pair this checklist with the CloudWatch metrics and the Performance Insights wait-event breakdown for the same window, which together cover what SQL cannot see.
- Aurora's storage layer grows in increments and never shrinks, so script 10's sizes describe logical object size; billed cluster-volume usage is a CloudWatch value (VolumeBytesUsed), not a SQL one.

## 8. Interpretation Guide

- Script 01 (cluster role) first, always: if you are not on the instance you think you are on, every subsequent result is being read about the wrong machine.
- Script 02 sizes the incident. An active session count around or above the instance's vCPU count means work is queueing for CPU; a large idle-in-transaction population means an application is leaking transactions; a normal profile despite a live report means the problem may not be in the database at all.
- Script 03 (wait events) is the single highest-signal result in the checklist. Lock-dominated means blocking; IO-dominated means resource pressure; LWLock or IPC means internal contention; few or no waits alongside many active sessions means genuine CPU-bound work.
- Script 04 is decisive when non-empty: any meaningful blocked-session count makes this a blocking incident first, whatever else the other scripts show, because nothing else can be fixed while the graph is stalled.
- Scripts 05 and 06 distinguish a long-running query from a long-running transaction. They are different problems: a long query costs resources; a long transaction holds the vacuum horizon and locks even when it is idle, which is often the quieter and more damaging of the two.
- Script 07 tells you how much time you have. Utilization near the ceiling means the incident will shortly become an availability incident regardless of its original cause, which raises the priority of every other finding.
- Script 08 attributes cumulative cost to specific statements, which no instantaneous snapshot can do -- rank by total time, not by mean.
- Script 09 explains the slow-burn causes: dead tuples accumulating because vacuum cannot advance past a long transaction, or vacuum workers competing with peak traffic.
- Script 10 rarely explains a sudden incident, but it catches the ones that are actually capacity problems, and it is the cheapest place to notice unbounded table growth before it becomes its own page.
- If all ten scripts look normal and the symptom persists, that is a genuine and valuable result: say so explicitly and redirect the investigation to the application, the pooler or the network rather than continuing to search the database.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- None from this workflow by design. It contains no remediation whatsoever -- its only output is an accurate picture and a routing decision.
- Take the first action from the guarded runbook of the specific workflow this checklist routes you to, so the action is taken with that workflow's preconditions and safety gates in force.

**Short-term remediation** (hours to days):

- Follow the short-term remediation of whichever workflow this checklist routed you to.
- Save the checklist output into the incident record while it is still accurate; the follow-up work is far cheaper when the evidence survives.

**Long-term engineering fix** (days to weeks):

- Automate this checklist as a scheduled snapshot (see the automation category) so a pre-incident baseline exists for comparison -- 'is this number normal' is otherwise the slowest question in every incident.
- Use repeated incidents to tune the checklist itself: if a step consistently produces nothing for your workload, and another question consistently matters, change the checklist rather than working around it.
- Train every on-call engineer to run these ten scripts before proposing any action, so triage discipline does not depend on who happens to be paged.

## 10. Production Safety

- Every script in this checklist is read-only and safe to run even during a live incident with no prior investigation -- that is the entire design goal of this workflow.
- No script here modifies data, takes anything beyond a brief catalog lock, cancels or terminates a session, changes configuration, or depends on an operator editing it first. All ten can be run blind, in order, by anyone with pg_monitor.
- The only extension-dependent script (08) is guarded, so a missing pg_stat_statements prints a notice and the checklist continues rather than erroring out mid-incident.
- All remediation deliberately lives elsewhere. If you find yourself wanting to act from inside this workflow, that is the signal that you have identified the specific workflow you should be in.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- The checklist cannot be completed because the database will not accept a connection -- escalate immediately and switch to the database-unavailable workflow and the disaster-recovery assessment in parallel.
- Script 01 shows a cluster role you did not expect (a writer that is now a reader) -- escalate on the failover track before interpreting anything else, because the topology changed underneath the incident.
- The checklist shows several independent anomaly classes at once -- treat it as a compound incident, declare a major incident, and assign a separate owner per track rather than working them sequentially.
- Order entry, deposits, withdrawals or settlement are affected -- escalate to treasury and compliance in parallel with the technical response, at the moment you know, not after resolution.
- All ten scripts are unremarkable while customer impact continues -- escalate outward to the application, platform and network teams; a clean database snapshot is strong evidence and should redirect the whole response.

## 12. Related Issues

- [database-unavailable](../database-unavailable/README.md)
- [sudden-latency-spike](../sudden-latency-spike/README.md)
- [high-cpu](../high-cpu/README.md)
- [connection-exhaustion](../connection-exhaustion/README.md)
- [lock-storm](../lock-storm/README.md)
- [runaway-query](../runaway-query/README.md)
- [application-timeouts](../application-timeouts/README.md)
- [post-deployment-incident](../post-deployment-incident/README.md)
- [comprehensive-health-check](../../database-health/comprehensive-health-check/README.md)
- [failover-investigation](../../replication-and-ha/failover-investigation/README.md)
