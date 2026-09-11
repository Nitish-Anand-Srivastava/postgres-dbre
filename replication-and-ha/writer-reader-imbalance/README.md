# Writer/Reader Load Imbalance

**Category:** Replication and High Availability | **Workflow:** `replication-and-ha/writer-reader-imbalance`

## 1. Problem Description

Investigates whether read traffic is effectively distributed across the reader fleet, or whether load is concentrated on the writer (under-utilizing readers) or unevenly distributed across readers.

## 2. Typical Symptoms

- Writer CPU/load elevated while readers show low utilization.
- One reader shows much higher load than its siblings despite similar instance classes.

## 3. Business Impact

- Failing to offload eligible read traffic to readers wastes provisioned reader capacity while unnecessarily loading the writer, which also serves all write traffic and cannot be scaled out horizontally the way readers can.

## 4. Possible Root Causes

- Application not using the reader endpoint for read-only queries at all (all traffic hardcoded to the writer/cluster endpoint).
- A custom query router unevenly distributing traffic across readers.
- A specific read-heavy feature routed to the writer for read-after-write consistency reasons, which is legitimate but should be a deliberate, documented choice, not a default.

## 5. Investigation Strategy

1. Compare session/query load on the writer vs. each reader.
2. Confirm application read/write query routing configuration.
3. For any read traffic deliberately routed to the writer, confirm the reasoning (consistency requirement) is documented.

## 6. Prerequisites

- Direct connection access to writer and each reader for comparison.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_writer_query_type_breakdown.sql`](scripts/01_writer_query_type_breakdown.sql) -- Breaks down query activity on the writer by application to identify read-heavy traffic that could potentially be offloaded to readers.

## 8. Interpretation Guide

- Some read traffic legitimately belongs on the writer (strict read-after-write requirements); the goal is intentional, documented routing, not zero writer reads.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- N/A.

**Short-term remediation** (hours to days):

- Update application data-access layer to route eligible read-only queries to the reader endpoint.

**Long-term engineering fix** (days to weeks):

- Establish a documented read/write routing policy per feature, balancing consistency requirements against writer load reduction.

## 10. Production Safety

- Read-only investigation.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- A large fraction of read-eligible traffic is found on the writer with no consistency justification -- escalate to the owning application team for a routing fix.

## 12. Related Issues

- [reader-performance](../reader-performance/README.md)
- [high-database-load](../../performance/high-database-load/README.md)
