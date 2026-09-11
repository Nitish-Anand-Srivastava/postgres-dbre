# Daily Health Check

**Category:** Database Health Checks | **Workflow:** `database-health/daily-health-check`

## 1. Problem Description

The lightweight morning sweep an on-call DBA runs every day before the busiest trading session: current load, connection headroom, the oldest open transaction, vacuum debt, transaction ID age, the slowest recurring statements, and reader lag. It is deliberately short enough to complete in a few minutes across every cluster in the fleet, and deliberately biased toward the small set of conditions that reliably turn into an exchange-wide incident if left unnoticed for another day.

## 2. Typical Symptoms

- No active symptom -- this is the scheduled daily routine, run at the start of the operational day and again before a known high-volume window (a token listing, a funding-rate settlement, a scheduled derivatives expiry).
- Used as the first response to a vague overnight alert that has since cleared and left no obvious trace.
- Used as the standing handover artifact between on-call shifts across regions.

## 3. Business Impact

- Most exchange database outages are slow-moving conditions that were observable for days before they became urgent: vacuum debt, XID age, connection creep, and reader lag all announce themselves well in advance if someone looks daily.
- A five-minute daily check that catches a single connection-headroom trend before a volatility spike prevents an outage during exactly the window where trading volume, and therefore revenue and reputational exposure, are highest.
- Daily readings build the trend data that make capacity planning an evidence-based conversation instead of a guess.

## 4. Possible Root Causes

- This workflow detects rather than root-causes: each finding hands off to the dedicated workflow that owns that failure mode.
- The recurring day-to-day causes it surfaces are gradual write growth outpacing autovacuum, connection-pool misconfiguration after a deployment, a forgotten batch job holding a transaction open overnight, and reader lag creeping up as writer WAL volume grows.

## 5. Investigation Strategy

1. Take a one-shot snapshot of current activity to see whether anything is abnormal right now.
2. Check connection headroom, the limit that turns a degradation into a hard outage fastest.
3. Check the oldest open transaction and any idle-in-transaction sessions, since they silently poison vacuum and locking.
4. Check vacuum debt on the highest-churn tables.
5. Check transaction ID age against the wraparound thresholds.
6. Check the slowest recurring statements for a day-over-day change.
7. Check reader lag, because read-path staleness is user-visible on an exchange even when the writer looks perfectly healthy.

## 6. Prerequisites

- Role membership in pg_monitor (or pg_read_all_stats).
- pg_stat_statements for the query step (the script prints a notice and continues if it is absent).
- Yesterday's output available for comparison -- the value of this workflow is almost entirely in the day-over-day delta, not the absolute readings.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_current_activity_snapshot.sql`](scripts/01_current_activity_snapshot.sql) -- One-shot snapshot of all backends grouped by state and wait event, to see whether anything is abnormal right now.
2. [`scripts/02_connection_headroom.sql`](scripts/02_connection_headroom.sql) -- Connection utilization against max_connections, plus a breakdown by application and user.
3. [`scripts/03_transaction_and_idle_check.sql`](scripts/03_transaction_and_idle_check.sql) -- Finds the oldest open transactions and any sessions sitting idle inside a transaction.
4. [`scripts/04_vacuum_debt_check.sql`](scripts/04_vacuum_debt_check.sql) -- Ranks tables by dead tuples and shows when autovacuum last reached each one.
5. [`scripts/05_xid_age_check.sql`](scripts/05_xid_age_check.sql) -- Checks transaction ID age per database against the wraparound-protection thresholds.
6. [`scripts/06_slowest_recurring_statements.sql`](scripts/06_slowest_recurring_statements.sql) -- Lists the slowest frequently-executed statements by mean execution time.
7. [`scripts/07_reader_lag_check.sql`](scripts/07_reader_lag_check.sql) -- Checks Aurora reader replication status and lag from any instance in the cluster.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Run the daily check against the cluster writer endpoint, not an instance endpoint: after a failover the instance endpoint may point at what is now a reader, and the connection/transaction/lock readings would silently describe the wrong instance.
- Cumulative counters reset on the promoted instance after an Aurora failover, so a day-over-day comparison across a failover will show apparent drops in every counter -- verify instance uptime before concluding a workload actually decreased.

## 8. Interpretation Guide

- Compare against yesterday first and against absolute thresholds second: a value that has been stable for months is far less interesting than one that moved 20% overnight.
- Expect a diurnal and weekly pattern on an exchange (Asian-hours volume, weekend derivatives activity, month-end reconciliation) and take today's reading at the same time of day as yesterday's, or the comparison is meaningless.
- If any check crosses its escalation threshold, stop the daily sweep and switch to the dedicated workflow for that condition -- do not finish the checklist first.
- A clean daily check is a legitimate, valuable result: record it, because the absence of change is itself the trend data that makes tomorrow's anomaly obvious.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Terminate nothing and change nothing from within this workflow -- it exists to detect and hand off.
- For an idle-in-transaction session older than the application's documented maximum transaction duration, notify the owning service team immediately; that is the single most common actionable daily finding.

**Short-term remediation** (hours to days):

- Raise a ticket for each threshold crossing with the captured output, and re-run the affected step after the fix to confirm the reading has returned to baseline.
- Schedule a targeted vacuum/analyze for any table whose vacuum debt has grown for several consecutive days.

**Long-term engineering fix** (days to weeks):

- Convert each daily check into an automated alert with the threshold this cluster has empirically proven appropriate, so the human daily pass becomes a verification rather than the primary detector.
- Track the daily readings in a time series so capacity and vacuum-tuning decisions are driven by trend lines rather than by the most recent incident.

## 10. Production Safety

- All scripts are strictly read-only and execute unmodified under default_transaction_read_only = on.
- Total runtime is a few seconds; this sweep is safe to run during peak trading hours and during an active incident.
- Run the connection, transaction, and lock steps against the cluster writer endpoint: on a reader they only describe that reader's own local sessions.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Connection utilization above 85%, or a jump of more than 20 percentage points versus yesterday.
- XID age above 50% of autovacuum_freeze_max_age, or any increase that would reach 100% before the next scheduled maintenance window.
- A transaction open longer than one hour, or any prepared transaction at all.
- Reader lag sustained above the application's read-your-own-write tolerance, since stale balance or order reads on an exchange generate support tickets and regulatory questions.

## 12. Related Issues

- [comprehensive-health-check](../comprehensive-health-check/README.md)
- [capacity-health-check](../capacity-health-check/README.md)
- [connection-exhaustion](../../connections/connection-exhaustion/README.md)
- [transaction-age](../../transactions-and-xid/transaction-age/README.md)
- [autovacuum-not-keeping-up](../../vacuum-and-autovacuum/autovacuum-not-keeping-up/README.md)
- [replication-lag](../../replication-and-ha/replication-lag/README.md)
