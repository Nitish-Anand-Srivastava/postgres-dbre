# Temporary File Growth Investigation

**Category:** Storage and Capacity | **Workflow:** `storage-and-capacity/temp-file-growth`

## 1. Problem Description

Queries are spilling sorts, hashes, and materializations to disk instead of completing in memory. Temporary files are a distinct storage problem from table growth: they consume per-instance local storage rather than the shared Aurora cluster volume, they appear and vanish within the lifetime of a single query, and they are nearly always a symptom of an undersized `work_mem` or a planner row-count misestimate rather than of genuine data volume. On an exchange platform the usual sources are reporting and reconciliation queries sorting large trade or ledger result sets, and hash joins whose build side the planner underestimated because statistics were stale.

## 2. Typical Symptoms

- CloudWatch `FreeLocalStorage` on an instance falls sharply during certain queries or batch windows, sometimes approaching zero.
- Queries fail outright with 'could not write to file' or 'temporary file size exceeds temp_file_limit'.
- `temp_bytes` in `pg_stat_database` climbs steadily throughout the trading day.
- Reporting or reconciliation queries have unpredictable runtimes -- fast most days, dramatically slower on high-volume days.
- Sessions are visibly waiting on `BufFileRead` or `BufFileWrite` wait events during peak periods.
- The PostgreSQL log is full of 'temporary file' lines when `log_temp_files` is enabled.

## 3. Business Impact

- Exhausting local storage on an instance causes query failures and, in the worst case, instance instability -- an availability event, not merely a slow query.
- Spilling converts an in-memory operation into a disk-based one, typically an order-of-magnitude slowdown, which pushes reconciliation and regulatory reporting past their windows.
- Temp file I/O competes with regular query I/O on the same instance, so one spilling report query degrades latency for unrelated trading traffic.
- Unpredictable query runtimes make capacity planning and SLA commitments for batch processes unreliable.

## 4. Possible Root Causes

- Memory sizing: `work_mem` set too low for the actual query shapes in production, so every large sort or hash spills.
- Memory sizing: `work_mem` is per sort/hash node, not per query -- a query with several such nodes running at high concurrency can use many multiples of the configured value, so administrators often set it conservatively and cause spills.
- Statistics: stale or insufficient statistics causing the planner to underestimate the build side of a hash join, so it allocates too little and spills mid-execution.
- Query shape: `ORDER BY` or `DISTINCT` over a large unindexed result set, where an appropriate index would allow an ordered index scan with no sort at all.
- Query shape: large `GROUP BY` aggregations over unfiltered history, typical of reconciliation and reporting queries run against the OLTP database.
- Query shape: a missing or non-selective predicate causing a join to process far more rows than the business question requires.
- Workload placement: analytics and reporting workloads running on the OLTP cluster instead of a dedicated reporting path.
- Volume: a genuine spike in matched trade volume producing legitimately larger intermediate result sets during a market event.

## 5. Investigation Strategy

1. Read cumulative temp file counters per database to establish scale and confirm which database is responsible.
2. Capture the memory-related configuration, since `work_mem` and `hash_mem_multiplier` determine the spill threshold for every node.
3. Attribute temp file volume to specific statements via `pg_stat_statements`, which is where the actionable finding usually is.
4. Look at what is spilling right now, so a live incident can be tied to a specific session and query.
5. List actual temporary files currently on disk to size the immediate local-storage exposure.
6. Check statistics freshness, because a planner misestimate is a far cheaper fix than a memory increase and is frequently the real cause.

## 6. Prerequisites

- `pg_monitor` role membership -- also required to execute `pg_ls_tmpdir()` for the on-disk listing script.
- `pg_stat_statements` installed for statement-level attribution.
- CloudWatch access for `FreeLocalStorage`, which is the authoritative measure of how much local scratch space remains on each instance.
- An understanding that temp files live on per-instance local storage, not the shared Aurora cluster volume -- the two have completely different limits and remediation.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_temp_file_usage_by_database.sql`](scripts/01_temp_file_usage_by_database.sql) -- Reports cumulative temporary file count and volume per database to establish scale and locate the responsible database.
2. [`scripts/02_memory_and_temp_settings.sql`](scripts/02_memory_and_temp_settings.sql) -- Captures the memory and temp file settings that determine when a sort or hash spills to disk.
3. [`scripts/03_temp_heavy_statements.sql`](scripts/03_temp_heavy_statements.sql) -- Attributes temporary file volume to individual statements, which is where the actionable finding almost always is.
4. [`scripts/04_sessions_spilling_now.sql`](scripts/04_sessions_spilling_now.sql) -- Shows currently active sessions and flags those waiting on temporary file I/O right now.
5. [`scripts/05_temp_files_on_disk.sql`](scripts/05_temp_files_on_disk.sql) -- Lists the temporary files physically present on this instance right now to size the immediate local-storage exposure.
6. [`scripts/06_statistics_freshness.sql`](scripts/06_statistics_freshness.sql) -- Checks planner statistics freshness, since a row-count misestimate causes spills that no amount of extra memory will prevent.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Temporary files consume per-instance local NVMe storage (`FreeLocalStorage` in CloudWatch), which is completely separate from the shared Aurora cluster volume (`VolumeBytesUsed`). You can exhaust local storage and fail queries while the cluster volume has terabytes of room -- and the reverse is equally possible.
- Local storage capacity scales with the instance class. Moving the reporting workload to a larger reader instance is a legitimate and sometimes the cheapest remediation, and it isolates the spill from the writer entirely.
- Aurora readers each have their own local storage and their own temp file usage. A reporting query spilling on a reader has no effect on the writer's local storage, which is a strong argument for pinning reporting traffic to a dedicated reader.
- `work_mem` is set through the Aurora DB cluster or instance parameter group. Per-role overrides via `ALTER ROLE ... SET work_mem` work normally and are the preferred way to give the reporting workload more memory without affecting the trading path.

## 8. Interpretation Guide

- Interpret `temp_bytes` as a rate, not a total: divide by the time since `stats_reset` to get bytes per hour, and compare that against the instance's `FreeLocalStorage` headroom to understand how much margin you actually have.
- A small number of statements almost always accounts for the large majority of temp bytes. Fix those and the problem usually disappears; there is rarely a need for a cluster-wide memory change.
- `work_mem` is allocated per sort or hash node per backend, not per query. A query plan with four such nodes running across fifty concurrent backends can consume two hundred times `work_mem` in the worst case -- this is precisely why raising it globally is dangerous and why a targeted session-level or role-level increase for the reporting workload is the safer fix.
- If `pct_modified_since_analyze` is high on the tables involved in a spilling query, fix statistics first. A planner that underestimates the build side of a hash join will spill no matter how much memory you give it, because it sized the hash table from a wrong estimate.
- A large sort on a column that could be served by an ordered index scan is a query and indexing problem, not a memory problem. Adding the right index eliminates the sort node entirely rather than making it cheaper.
- Sessions waiting on `BufFileRead` or `BufFileWrite` are actively reading or writing temp files right now -- that is a live spill, and the query text on that row is your culprit.
- Temp files that persist on disk for a long time usually belong to a still-running query. Files left behind by a crashed backend are cleaned up on the next instance restart, so a growing count of old files with no matching active session is worth noting.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If local storage is close to exhausted, stop the offending report or batch job at the application layer -- this is the fastest safe lever.
- Raise `work_mem` for the single offending session or role (`SET work_mem`, or `ALTER ROLE reporting SET work_mem`), never globally as a reflex during an incident.
- If a specific runaway query is spilling unboundedly, have the owning team cancel it through their application rather than reaching for backend termination as a first response.

**Short-term remediation** (hours to days):

- Run `ANALYZE` on the tables involved in the spilling queries so the planner sizes its hash tables and sorts from accurate row counts.
- Set a higher `work_mem` on the reporting role specifically, isolating the increase to the workload that needs it and leaving the trading path untouched.
- Add the index that lets the worst sorting query use an ordered index scan instead of an explicit sort.
- Add or tighten predicates on reporting queries so they process the business-relevant window rather than full history.
- Set `temp_file_limit` as a guardrail so a single runaway query fails fast instead of filling local storage and destabilizing the instance.

**Long-term engineering fix** (days to weeks):

- Move reporting, reconciliation, and analytics workloads off the OLTP cluster to a dedicated reader, a separate reporting database, or an analytics store.
- Introduce pre-aggregated summary tables for the recurring reconciliation and regulatory reports instead of recomputing them from raw trade and ledger history every run.
- Right-size instance classes for the reporting path: local storage scales with instance size on Aurora, so a larger reader is a legitimate answer for a genuinely memory-hungry workload.
- Set an appropriate per-table statistics target on the columns that drive join and filter estimates for the big reporting queries.
- Add temp file rate to routine monitoring so a growing spill trend is a scheduled conversation rather than an incident.

## 10. Production Safety

- All scripts here are read-only.
- The on-disk temp file listing uses `pg_ls_tmpdir()`, which requires `pg_monitor` membership; the script checks role membership first and prints guidance rather than failing for an under-privileged role.
- Temp file listings are per-instance. Run them on the instance that is actually reporting low `FreeLocalStorage`, not on whichever instance you happen to be connected to.
- Do not raise `work_mem` cluster-wide during an incident. The parameter is allocated per node per backend, so a global increase under high concurrency can turn a disk-spill problem into an out-of-memory problem.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- `FreeLocalStorage` on any instance is approaching zero -- this is an availability risk and should be treated as an incident, with the offending workload stopped immediately.
- Queries are failing with temp file write errors on the writer, meaning the trading path is affected rather than only reporting.
- Temp file volume has grown sharply with no query change, no volume change, and no statistics drift -- involve application engineering to identify a changed access pattern.
- The correct fix requires a larger instance class or a new reporting architecture -- that is a cost and design decision for engineering leadership.

## 12. Related Issues

- [unexpected-storage-growth](../unexpected-storage-growth/README.md)
- [capacity-forecasting](../capacity-forecasting/README.md)
- [sort-spills](../../query-optimization/sort-spills/README.md)
- [temp-file-investigation](../../query-optimization/temp-file-investigation/README.md)
- [stale-statistics](../../query-optimization/stale-statistics/README.md)
- [high-iops](../../performance/high-iops/README.md)
