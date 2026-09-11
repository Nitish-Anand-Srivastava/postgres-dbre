# High Database Load (Average Active Sessions)

**Category:** Performance Issues | **Workflow:** `performance/high-database-load`

## 1. Problem Description

The database is showing a sustained high number of active/waiting sessions (high 'load' in the Performance Insights / AAS sense) even if instance CPU itself is not yet saturated. Unlike high-cpu, this workflow starts from the load composition (what sessions are doing) rather than assuming CPU is the bottleneck.

## 2. Typical Symptoms

- Performance Insights Database Load graph exceeding the instance's vCPU count for a sustained period.
- Growing number of sessions in pg_stat_activity across all states (active, idle in transaction, waiting on locks).
- Increasing p95/p99 latency without a single obviously dominant query.

## 3. Business Impact

- High load is a leading indicator that precedes CPU/IO saturation and outright timeouts -- catching it early prevents a full incident.
- In a high-throughput exchange, load spikes often correlate with market volatility events where correctness and availability both matter most.

## 4. Possible Root Causes

- Application-level: retry storms, connection leaks, or a new feature generating far more queries per request than expected.
- Query-level: a mix of moderately expensive queries whose combined effect saturates capacity (no single 'smoking gun').
- Concurrency-level: growing lock wait queues amplifying apparent load (waiting sessions still count toward AAS).
- Vacuum-level: multiple autovacuum workers running concurrently against large hot tables during peak hours.
- Capacity-level: genuine organic growth outpacing the current instance class / reader fleet size.

## 5. Investigation Strategy

1. Break down current load by wait_event_type/wait_event to see the composition (CPU vs Lock vs IO vs IPC vs Client).
2. Break down load by database and application_name to see which service/tenant is driving it.
3. Check pg_stat_statements for the queries contributing the most total execution time in the current window.
4. Check autovacuum activity, since concurrent vacuum workers count toward load and compete for the same resources as application queries.
5. Compare current connection counts against max_connections headroom, since a growing backlog can itself be both a symptom and an amplifier.

## 6. Prerequisites

- pg_stat_statements recommended (script 03) but not mandatory to begin the investigation.
- AWS Performance Insights enabled is strongly recommended for this workflow specifically, since it provides a ready decomposition of AAS by wait type and top SQL without needing to poll pg_stat_activity manually.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_load_composition_by_wait_event.sql`](scripts/01_load_composition_by_wait_event.sql) -- Breaks current session load down by wait_event_type/wait_event to identify the dominant contributor.
2. [`scripts/02_load_by_application_and_database.sql`](scripts/02_load_by_application_and_database.sql) -- Breaks load down by application_name/usename/datname to identify which service or tenant is driving it.
3. [`scripts/03_top_queries_by_total_time.sql`](scripts/03_top_queries_by_total_time.sql) -- Identifies the queries contributing the most cumulative execution time in the current window.
4. [`scripts/04_autovacuum_contribution.sql`](scripts/04_autovacuum_contribution.sql) -- Checks whether concurrent autovacuum workers are a meaningful contributor to current load.
5. [`scripts/05_connection_headroom.sql`](scripts/05_connection_headroom.sql) -- Checks connection count against max_connections headroom, since a growing backlog itself compounds load.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Average Active Sessions (AAS) as displayed in Performance Insights is an AWS-computed metric; there is no single PostgreSQL catalog column that reproduces it exactly, though the scripts here approximate it via point-in-time pg_stat_activity snapshots.

## 8. Interpretation Guide

- AAS (Average Active Sessions) > number of vCPUs sustained for minutes, not seconds, is the actionable threshold -- brief spikes are normal.
- If load composition is dominated by one wait_event, pivot directly to the matching specialized workflow (Lock -> concurrency-and-locking, IO -> storage-and-capacity, CPU/NULL -> high-cpu).
- Autovacuum contributing a large share of load on its own is not inherently bad -- it means autovacuum is doing necessary work; the question is whether its cost limits should be tuned to spread the work over a longer window instead of running at full throttle during peak hours.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Route eligible read-only traffic to reader endpoint(s) to redistribute load away from the writer.
- If a specific application/tenant is identified as the driver, engage that team to pause/rate-limit the offending traffic.

**Short-term remediation** (hours to days):

- Tune autovacuum cost-based delay settings so background maintenance does not compete with peak-hour traffic (see vacuum-and-autovacuum/autovacuum-not-keeping-up).
- Add missing indexes / fix moderately expensive queries identified in pg_stat_statements even if none is individually dominant.

**Long-term engineering fix** (days to weeks):

- Capacity plan for observed growth trend (see storage-and-capacity/capacity-forecasting) and pre-provision reader capacity ahead of anticipated volatility events.
- Introduce application-level rate limiting / backpressure so a downstream retry storm cannot translate directly into database load.

## 10. Production Safety

- All scripts are read-only.
- Do not disable autovacuum to 'reduce load' -- this defers cost and risks a much worse emergency-autovacuum situation later (see vacuum-and-autovacuum/emergency-autovacuum).

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Load composition points to an application-level retry storm or leak -- escalate to the owning application team immediately, in parallel with continued DB-side investigation.
- Sustained load approaching 2x the instance's vCPU count with no single fixable root cause -- this is a capacity decision, escalate to database engineering leadership.

## 12. Related Issues

- [high-cpu](../high-cpu/README.md)
- [comprehensive-health-check](../../database-health/comprehensive-health-check/README.md)
- [performance-insights](../../observability/performance-insights/README.md)
