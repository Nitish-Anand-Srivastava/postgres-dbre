# Reader Lag Deep-Dive Investigation

**Category:** Replication and High Availability | **Workflow:** `replication-and-ha/reader-lag-investigation`

## 1. Problem Description

A deeper, more structured investigation than replication-lag for cases where initial checks did not resolve the cause, walking through writer write-rate, storage I/O, and reader-side factors systematically.

## 2. Typical Symptoms

- replication-lag's initial checks did not identify a clear cause.
- Lag is intermittent/bursty rather than sustained, making correlation harder.

## 3. Business Impact

- Same as replication-lag; this workflow exists for cases requiring a more systematic, multi-factor investigation.

## 4. Possible Root Causes

- A combination of factors (moderate write volume plus a moderately undersized reader) rather than one single dominant cause.
- Bursty batch/reporting workloads on the writer periodically spiking WAL generation.

## 5. Investigation Strategy

1. Re-confirm current lag levels across all readers.
2. Correlate lag spikes against writer WAL generation over the same time window.
3. Correlate lag spikes against checkpoint activity on the writer.
4. Check for reader-side long-running queries at the same timestamps.

## 6. Prerequisites

- Ability to correlate timestamps across writer and reader observations -- ideally via CloudWatch metrics correlation in addition to these SQL snapshots.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_all_readers_lag_snapshot.sql`](scripts/01_all_readers_lag_snapshot.sql) -- Snapshots lag across every reader in the cluster simultaneously for cross-reader comparison.
2. [`scripts/02_writer_checkpoint_correlation.sql`](scripts/02_writer_checkpoint_correlation.sql) -- Checks writer checkpoint activity to correlate against lag spikes.

## 8. Interpretation Guide

- Bursty lag correlating with periodic batch jobs (e.g. an hourly reporting query on the writer generating heavy WAL) points to a scheduling fix (move the batch job off-peak or to a reader) rather than a capacity fix.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- N/A -- deep-dive investigation, not an emergency workflow itself.

**Short-term remediation** (hours to days):

- Reschedule identified WAL-heavy batch jobs to lower-traffic windows.

**Long-term engineering fix** (days to weeks):

- See replication-lag's long-term guidance.

## 10. Production Safety

- Read-only.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- No clear pattern emerges after this deeper investigation -- open an AWS Support case with the gathered evidence.

## 12. Related Issues

- [replication-lag](../replication-lag/README.md)
