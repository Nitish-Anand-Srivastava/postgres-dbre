# Runaway Query

**Category:** Incident Response | **Workflow:** `incident-response/runaway-query`

## 1. Problem Description

A single query is consuming a disproportionate share of the instance's resources -- running for minutes on an OLTP path, spilling gigabytes of temp files, holding locks that other sessions need, or all three. This workflow identifies it precisely, quantifies what it is actually costing, and stops it with the smallest possible intervention.

## 2. Typical Symptoms

- One session in pg_stat_activity with a query_runtime orders of magnitude above everything else.
- A temp-file volume spike with no corresponding growth in legitimate workload.
- Other sessions blocked behind the one long-running statement.
- A reporting, export or reconciliation query accidentally pointed at the writer instead of a reader.
- An unbounded query -- a missing WHERE clause, a missing join predicate, or a parameter that arrived as NULL and matched everything.

## 3. Business Impact

- A runaway query on the writer competes directly with order and ledger writes for CPU, memory and IO, so one careless analytical statement can degrade the entire trading platform.
- If it holds locks, it converts into a lock storm and stops the affected tables completely.
- Long-running queries hold back the vacuum horizon for as long as they run, so a query left alone for hours also leaves behind bloat and a delayed freeze horizon.

## 4. Possible Root Causes

- A missing or non-selective predicate, so the query scans the whole table (or the whole partition set) instead of a narrow range.
- A plan regression: the statement was fine yesterday, and stale statistics or a data-distribution change flipped it to a nested loop over a large set.
- An analytical or export query run against the writer instead of a reader endpoint, often by a human in a console.
- A parameter binding bug, most commonly a NULL or an empty filter list that widens the result set to everything.
- A cartesian product from a forgotten join condition in a hand-written operational query.
- A one-off data-fix or backfill statement run without batching during trading hours.

## 5. Investigation Strategy

1. Find the candidates: active queries running far longer than the workload's normal profile.
2. Pull full forensic detail on the specific backend, including the complete query text, its transaction age, and how many other sessions it is blocking.
3. Quantify the collateral damage: is it blocking anything, and is it spilling temp files or driving IO?
4. Check the statement's history to distinguish a normally-fine statement that regressed from a statement that has always been expensive.
5. Stop it with the smallest intervention that works -- cancel first, terminate only if cancel fails and the safety gate is satisfied.

## 6. Prerequisites

- `pg_monitor` role membership, plus `pg_signal_backend` (or `rds_superuser`) to stop the query.
- A way to identify the query's owner: application_name, usename, or client_addr. Without an owner, you cannot judge whether stopping it is safe.
- `pg_stat_statements` for the history check (optional -- the script prints a notice if absent).

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_runaway_candidates.sql`](scripts/01_runaway_candidates.sql) -- Lists the active queries running far longer than the workload's normal profile, to identify the candidate.
2. [`scripts/02_target_backend_detail.sql`](scripts/02_target_backend_detail.sql) -- Captures complete forensic detail for the specific backend, including its full query text and how many sessions it is blocking.
3. [`scripts/03_collateral_damage.sql`](scripts/03_collateral_damage.sql) -- Quantifies what the runaway is costing everyone else: sessions blocked behind it and temp-file pressure across the database.
4. [`scripts/04_statement_history.sql`](scripts/04_statement_history.sql) -- Checks whether this statement shape has always been expensive or has recently regressed.
5. [`scripts/05_stop_the_runaway_query.md`](scripts/05_stop_the_runaway_query.md) -- Guarded runbook for stopping a runaway query with the smallest intervention that actually works, and for handling the open-transaction case correctly.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- A runaway query on an Aurora reader consumes that reader's CPU and memory but cannot block writer traffic on locks, because readers serve read-only snapshots -- which is exactly why routing analytical work to readers is the durable fix rather than a workaround.
- Temp files on Aurora are written to the instance's local storage, which is finite and separate from the cluster volume; a query spilling aggressively can exhaust local storage and fail with a disk-full error that has nothing to do with your cluster's actual data size.
- Aurora Performance Insights retains the statement text for top consumers even after the session ends, which is often the only remaining evidence once a runaway has been terminated -- check there if the query text was not captured in time.

## 8. Interpretation Guide

- The full query text from script 02 is the single most important artifact in this workflow. Capture it before you act: once the backend is gone, pg_stat_activity retains nothing.
- sessions_this_backend_blocks greater than zero changes the urgency completely -- the runaway is now also a blocker, and the incident is a lock storm in the making.
- A txn_runtime much larger than the query_runtime means this statement is part of a longer transaction, so cancelling the statement leaves the transaction (and its locks and snapshot) open. In that case cancel, then require the client to end its transaction, or terminate.
- Large temp_blks_written against the statement's history means it is spilling sorts or hashes to disk, which is both a symptom of an undersized work_mem and a large driver of IO.
- A statement with a high historical mean that has always been slow is a candidate to move to a reader, not necessarily to kill on sight.
- backend_type that is not `client backend` means this is not an application query at all -- never signal it; escalate instead.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Cancel the specific backend after capturing the query text and confirming ownership.
- If the statement is part of an open transaction, follow the cancel by confirming with the owner that their client ends the transaction -- otherwise the locks and snapshot survive the cancel.
- If cancel has demonstrably failed and the safety gate is satisfied, terminate.
- Tell the owner before they retry: an unmodified retry reproduces this incident within minutes.

**Short-term remediation** (hours to days):

- Set `statement_timeout` for the role that ran it, so the same class of query fails fast next time instead of running for an hour.
- Point reporting, export and ad-hoc analytical work at the reader endpoint, and make that the default in the tooling rather than a convention.
- Add the missing index or predicate the query needed, following the concurrent index build pattern.

**Long-term engineering fix** (days to weeks):

- Give analysts and operators a dedicated read-only role on the reader endpoint with a conservative statement_timeout baked into the role, so the safe path is also the easy path.
- Require batching for all data-fix and backfill statements, with an explicit chunk size and commit interval.
- Alert on any single query exceeding a duration threshold on the writer, so runaways are caught by monitoring rather than by customers.

## 10. Production Safety

- Scripts 01-04 are read-only. Script 02 is explicitly safe to run unedited: its :target_pid defaults to 0, which matches no backend, so an unedited run simply returns no rows.
- Script 05 ends a session and must be read fully before use.
- Capture the full query text before stopping anything. Acting first and investigating afterwards destroys the only evidence that explains the incident.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- The runaway is a settlement, reconciliation or withdrawal-processing statement -- escalate to treasury and compliance before stopping it, because a partially applied financial batch is worse than a slow one.
- The backend is not a client backend -- escalate to database engineering and do not signal it.
- Cancel and terminate both fail to stop it, which points at a stuck backend and warrants an AWS support case.
- The same runaway shape recurs after remediation, which means the fix is upstream in the application or in analyst tooling rather than in this incident.

## 12. Related Issues

- [production-triage](../production-triage/README.md)
- [high-cpu](../high-cpu/README.md)
- [sudden-latency-spike](../sudden-latency-spike/README.md)
- [lock-storm](../lock-storm/README.md)
- [high-cpu](../../performance/high-cpu/README.md)
