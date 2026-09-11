# Performance Degradation After Failover

**Category:** Performance Issues | **Workflow:** `performance/performance-after-failover`

## 1. Problem Description

Performance degraded following an Aurora failover (planned or unplanned) -- most commonly because the newly promoted writer starts with a cold buffer cache and must re-warm it from Aurora storage under live production load.

## 2. Typical Symptoms

- Elevated latency/IOPS immediately following a failover event, gradually improving over minutes.
- Application connection errors/retries at the moment of failover (expected, brief) followed by a slower-than-normal recovery period.
- CloudWatch showing a new writer instance identity at the failover timestamp.

## 3. Business Impact

- Failover is a designed-for HA mechanism, but the post-failover performance dip is real and, if not anticipated, can be mistaken for a new unrelated incident -- wasting response time.
- For a trading platform, even a brief post-failover degradation window can affect order execution during exactly the period when resilience matters most.

## 4. Possible Root Causes

- Cold buffer cache on the newly promoted writer: shared_buffers starts empty and must be repopulated from Aurora shared storage.
- Connection storm as application connection pools reconnect simultaneously after the failover-induced disconnect.
- Query plans that were cached (prepared statement generic plans) are invalidated by the new connections' fresh sessions, temporarily increasing planning overhead.
- Any lock/vacuum state from the previous writer does not carry over -- this is not usually a cause, but should be confirmed, not assumed.

## 5. Investigation Strategy

1. Confirm the failover occurred and identify the exact timestamp and new writer instance identity.
2. Check current buffer cache hit ratio to confirm and quantify the cold-cache effect.
3. Check current connection counts/rate to assess whether a reconnect storm is compounding the cold-cache effect.
4. Check whether performance is recovering over time (re-run the cache hit ratio check every few minutes) to distinguish an expected, resolving warm-up from a separate, non-failover-related problem.

## 6. Prerequisites

- AWS Console/CloudWatch or RDS Events access to confirm failover timestamp and new writer identity.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_confirm_recovery_role_and_uptime.sql`](scripts/01_confirm_recovery_role_and_uptime.sql) -- Confirms this instance's current writer/reader role and how recently it started, to verify a failover occurred.
2. [`scripts/02_cache_warmup_progress.sql`](scripts/02_cache_warmup_progress.sql) -- Tracks buffer cache hit ratio to quantify and monitor cold-cache recovery progress.
3. [`scripts/03_reconnect_storm_check.sql`](scripts/03_reconnect_storm_check.sql) -- Checks current connection count/composition for a reconnect storm compounding the cache warm-up effect.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Aurora failover typically completes (DNS/endpoint cutover) within seconds to tens of seconds, which is fast relative to traditional PostgreSQL replica promotion, but the buffer cache warm-up period afterward is a separate, workload-dependent duration that Aurora's fast failover does not eliminate.

## 8. Interpretation Guide

- A cache hit ratio that starts low immediately after failover and steadily climbs back toward baseline over minutes is the expected, self-resolving pattern -- communicate this clearly to stakeholders rather than treating it as a new open-ended incident.
- If the cache hit ratio does NOT recover within a reasonable window (worse than pre-failover baseline warm-up times), or another symptom (locks, specific query errors) persists, treat it as a separate incident and pivot to sudden-performance-degradation.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- None required if this is expected post-failover cache warm-up -- monitor and communicate expected recovery time to stakeholders.
- If a reconnect storm is overwhelming the new writer, ensure application-side connection retry logic includes jitter/backoff (an application-side fix, not a database one).

**Short-term remediation** (hours to days):

- Consider a brief post-failover warm-up routine (running a set of representative read queries) for critical hot tables if warm-up time is a recurring pain point.

**Long-term engineering fix** (days to weeks):

- Evaluate Aurora's fast failover characteristics and, if warm-up time is a recurring business risk, discuss a maintained warm standby / connection draining strategy with the platform team.
- Add failover drills (see disaster-recovery/cluster-failover-drill) to regularly measure and track actual warm-up duration.

## 10. Production Safety

- All scripts are read-only.
- Do not attempt to force a second failover or restart the instance while it is still warming up -- this resets progress and extends the degraded period.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Cache hit ratio and latency do not show any recovery trend after 15-20 minutes -- escalate as a distinct incident rather than continuing to assume normal warm-up.

## 12. Related Issues

- [sudden-performance-degradation](../sudden-performance-degradation/README.md)
- [failover-investigation](../../replication-and-ha/failover-investigation/README.md)
- [cluster-failover-drill](../../disaster-recovery/cluster-failover-drill/README.md)
