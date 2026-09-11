# Transaction Age Monitoring

**Category:** Transaction ID (XID) Wraparound and Transaction Management | **Workflow:** `transactions-and-xid/transaction-age`

## 1. Problem Description

Routine, lower-urgency monitoring of transaction ID age across databases and tables -- the proactive counterpart to xid-wraparound-risk, intended for regular health checks rather than active-incident response.

## 2. Typical Symptoms

- No active symptom -- this workflow is proactive/preventative and is typically run on a schedule (see automation/xid-monitoring) rather than triggered by an incident.

## 3. Business Impact

- Regular transaction-age monitoring is what keeps xid-wraparound-risk a theoretical scenario instead of a recurring incident.

## 4. Possible Root Causes

- N/A -- this is a monitoring workflow, not an incident investigation. See xid-wraparound-risk for root-cause analysis once elevated age is found.

## 5. Investigation Strategy

1. Run the database- and table-level age checks on a schedule.
2. Compare against threshold percentages of autovacuum_freeze_max_age.
3. Escalate to xid-wraparound-risk immediately if any threshold is breached.

## 6. Prerequisites

- pg_monitor role membership.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_database_age_snapshot.sql`](scripts/01_database_age_snapshot.sql) -- Routine database-level XID age snapshot for scheduled monitoring.
2. [`scripts/02_table_age_snapshot.sql`](scripts/02_table_age_snapshot.sql) -- Routine table-level XID age snapshot, top N oldest tables.

## 8. Interpretation Guide

- Track age trend over time (via automation/xid-monitoring's historical snapshots), not just the current value -- a slowly climbing trend is actionable long before a single snapshot looks alarming.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- None required at healthy age levels; if a threshold is breached, proceed directly to xid-wraparound-risk.

**Short-term remediation** (hours to days):

- Tune autovacuum settings proactively if age is trending toward, but not yet at, a concerning threshold.

**Long-term engineering fix** (days to weeks):

- Automate this check (automation/xid-monitoring) and alert at a conservative threshold (e.g. 40-50% of autovacuum_freeze_max_age) well ahead of any urgency.

## 10. Production Safety

- All scripts are read-only.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Any database or table age exceeds 75% of autovacuum_freeze_max_age -- escalate to the full xid-wraparound-risk workflow.

## 12. Related Issues

- [xid-wraparound-risk](../xid-wraparound-risk/README.md)
- [xid-monitoring](../../automation/xid-monitoring/README.md)
