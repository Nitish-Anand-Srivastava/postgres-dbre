# Temporary File Investigation

**Category:** Query Optimization | **Workflow:** `query-optimization/temp-file-investigation`

## 1. Problem Description

Temporary files are PostgreSQL's overflow mechanism: any operation that exceeds its memory budget -- a sort, a hash join, a hash aggregate, a materialized CTE, a large cursor -- writes the excess to local instance storage. This workflow is the instance-level view: how much temporary file volume exists, which statements produce it, which sessions are producing it right now, and whether the configuration makes it visible at all. It is where an unexplained I/O or storage symptom is traced back to a specific statement.

## 2. Typical Symptoms

- Rising temp_bytes on pg_stat_database with no obvious workload change.
- Elevated local storage I/O or an unexplained latency increase that does not correlate with query volume.
- Sessions waiting on IO wait events such as BufFileRead and BufFileWrite.
- Log entries reporting temporary file creation, or a local storage capacity alert on the instance.

## 3. Business Impact

- Temporary file I/O competes directly with the trading workload for the instance's I/O capacity, so heavy spilling by a background report degrades order placement and balance lookups that are nowhere near it in the code.
- Local instance storage is finite and not shared with the Aurora cluster volume: exhausting it causes queries to fail outright with an out-of-space condition rather than merely slowing down.
- Because the excess is invisible in table sizes and in the cluster volume, unexplained temporary file growth is frequently misdiagnosed as a hardware or Aurora platform problem when it is in fact one query with an undersized memory budget.

## 4. Possible Root Causes

- work_mem too small for the workload's sorts, hashes, and aggregates -- the dominant cause.
- Row underestimates leading the planner to choose memory-hungry plans it believed would be small.
- Large analytical or export queries running against the writer instead of a dedicated reader.
- Deep OFFSET pagination and unbounded exports sorting far more rows than they return.
- Materialized CTEs and large cursors holding intermediate result sets on disk.
- Parallel query multiplying per-worker memory demand beyond what a single work_mem value suggests.
- log_temp_files left disabled, so spills accumulate unobserved until they become a capacity problem.

## 5. Investigation Strategy

1. Quantify the cluster-wide temporary file volume and rate per database.
2. Attribute the volume to specific statements through pg_stat_statements.
3. Catch sessions that are spilling right now, using the temporary-file I/O wait events.
4. Check the memory and logging configuration, including whether spills are being logged at all.
5. Correlate the findings with the logs and reproduce safely under the guarded runbook.

## 6. Prerequisites

- Role membership in pg_monitor (or pg_read_all_stats).
- pg_stat_statements for statement-level attribution.
- log_temp_files set to 0 for complete visibility, with Aurora log export to CloudWatch Logs enabled so the entries are searchable.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_temp_file_volume_by_database.sql`](scripts/01_temp_file_volume_by_database.sql) -- Quantifies cumulative temporary file volume and rate per database.
2. [`scripts/02_statements_producing_temp_files.sql`](scripts/02_statements_producing_temp_files.sql) -- Attributes temporary file volume to specific normalized statements.
3. [`scripts/03_sessions_spilling_now.sql`](scripts/03_sessions_spilling_now.sql) -- Catches sessions currently performing temporary file I/O, using the BufFile wait events.
4. [`scripts/04_memory_and_logging_settings.sql`](scripts/04_memory_and_logging_settings.sql) -- Reviews the memory budget, the temp file limit, and whether spills are being logged.
5. [`scripts/05_correlate_and_reproduce_safely.md`](scripts/05_correlate_and_reproduce_safely.md) -- Guarded runbook for correlating temporary files with statements via the logs and reproducing a spill safely.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Temporary files live on local instance storage, separate from the shared Aurora cluster volume. They do not appear in VolumeBytesUsed and their capacity is a property of the instance class, so the relevant CloudWatch metric is FreeLocalStorage rather than any cluster storage metric.
- log_temp_files is set through the Aurora DB cluster parameter group and takes effect without a reboot; the resulting log lines are exported to CloudWatch Logs, where they can be searched and aggregated across the fleet.
- Because each instance has its own local storage, moving analytical work to a reader moves its temporary file footprint there too -- which is precisely the point, as it removes that I/O from the writer's order path.

## 8. Interpretation Guide

- pg_stat_database.temp_bytes is cumulative since stats_reset and counts every temporary file written by every backend. Convert it to a rate before comparing anything.
- pg_stat_statements attributes temporary blocks to normalized statements, which is what turns 'the instance is spilling' into 'this specific query is spilling'. Without the extension, the log is the only attribution path.
- The BufFileRead and BufFileWrite wait events indicate a backend actively reading or writing temporary files at this instant. Catching them requires sampling pg_stat_activity repeatedly during the problem window, since each spill may be brief.
- Temporary file volume is a symptom, never a root cause. The actual cause is always either insufficient memory for a legitimate operation, or a plan that should not have needed that much memory in the first place -- and only the plan distinguishes them.
- A steady low-level spill rate from a very high-frequency statement is usually more damaging to an exchange than a large occasional spill from a monthly report, because it consumes I/O continuously in the request path.
- On Aurora, temporary file space is local instance storage. It does not appear in VolumeBytesUsed, it is not shared between instances, and running out of it is an instance-level failure rather than a cluster-level one.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If local storage is close to exhaustion, stop or defer the largest spilling workloads first -- typically a report or export, not the trading path.
- Move a large one-off analytical query to a reader instance rather than letting it continue on the writer.

**Short-term remediation** (hours to days):

- Raise work_mem for the specific role running the spilling workload, after sizing it with the sort-spills or hash-join-analysis runbook.
- Enable log_temp_files (value 0) so every future spill is attributed automatically instead of being reconstructed from counters.
- Run targeted ANALYZE where a row underestimate caused a memory-hungry plan.

**Long-term engineering fix** (days to weeks):

- Route analytical, export, and reconciliation workloads to dedicated Aurora readers with their own parameter group sized for spilling work.
- Set temp_file_limit for analytical roles so a runaway query fails fast instead of consuming the instance's entire local storage.
- Replace OFFSET pagination and unbounded exports with keyset pagination and chunked exports across the exchange's history and reporting endpoints.

## 10. Production Safety

- All .sql scripts here are read-only and safe during trading hours.
- Reproducing a spilling statement executes it and produces the same temporary file I/O again, which is why reproduction is a guarded runbook step and should happen on a reader. Deciding to actually execute a candidate production query is an operator judgement call, not something an investigation script may do on the operator's behalf. That is why every EXPLAIN ANALYZE step in this toolkit is a markdown runbook rather than a .sql file.
- Setting temp_file_limit is a safety control, not a tuning knob: it causes offending queries to fail rather than to exhaust storage, and that trade-off must be agreed with the workload owner before it is applied.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Local instance storage is close to exhaustion -- escalate immediately, because the failure mode is query errors rather than slow queries.
- Temporary file volume rose sharply with no identifiable statement and no deployment to explain it.
- The spilling workload cannot be moved off the writer and cannot be given more memory safely -- escalate for a topology or instance-class decision.

## 12. Related Issues

- [sort-spills](../sort-spills/README.md)
- [hash-join-analysis](../hash-join-analysis/README.md)
- [analyze-query-plan](../analyze-query-plan/README.md)
- [high-iops](../../performance/high-iops/README.md)
- [capacity-health-check](../../database-health/capacity-health-check/README.md)
