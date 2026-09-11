# Baseline Aurora PostgreSQL DBA Dashboard Recommendations

**Category:** Observability | **Workflow:** `observability/dashboard-recommendations`

## 1. Problem Description

A proposed baseline layout for a team building its own always-on Grafana/CloudWatch dashboard for an Aurora PostgreSQL fleet, grouping the signals from postgres-metrics, performance-insights, cloudwatch, slow-query-observability, and wait-event-analysis into a coherent set of panels. This workflow is primarily documentation: the goal is a concrete starting layout a platform team can implement immediately, plus a single-row query that can back a simple 'cluster at a glance' panel without any other tooling.

## 2. Typical Symptoms

- No active symptom -- this workflow is used when standing up a new dashboard, or auditing an existing one against a documented baseline.
- An incident review finds that a signal which would have shown the problem developing was being collected (per postgres-metrics) but was never actually placed on a dashboard anyone looks at regularly.
- Multiple teams each maintain their own ad hoc dashboard with inconsistent coverage, and a shared baseline is needed.

## 3. Business Impact

- A dashboard that is actually watched continuously catches the same slow-moving conditions (connection creep, vacuum debt, XID age, reader lag) that daily-health-check catches, but earlier and without requiring someone to remember to run a check.
- A well-organized dashboard shortens every future incident's first few minutes, since the on-call engineer starts from an already-visible picture of load, replication, and vacuum health instead of reconstructing it live under time pressure.
- Consistent dashboard coverage across every cluster in the fleet means an engineer on-call for a cluster they do not normally own can orient just as quickly as the cluster's regular owner.

## 4. Possible Root Causes

- Not a failure workflow -- this is a documentation/planning workflow proposing a dashboard structure.
- The most common gap this closes: a dashboard built early and never revisited, covering only the CloudWatch-visible basics (CPU, connections) while database-internal signals (vacuum, XID age, query-level stats, wait events) are collected but never actually surfaced anywhere a human looks routinely.

## 5. Investigation Strategy

1. Inventory what is already on the existing dashboard (if any) against the panel groups proposed below.
2. For each proposed panel group, identify the specific CloudWatch metric and/or SQL script from this repository that backs it.
3. Prioritize adding the panel groups this cluster's own incident history shows would have helped most (see database-health/comprehensive-health-check for how to establish that history).
4. Use the single-row snapshot query as a quick starting data source for a 'cluster at a glance' panel while the fuller per-panel queries are being wired up individually.

## 6. Prerequisites

- A dashboarding tool already in use or planned (Grafana with a PostgreSQL and/or CloudWatch data source, or CloudWatch dashboards directly).
- Role membership in pg_monitor (or pg_read_all_stats) for the dashboard's PostgreSQL data source connection.
- The individual metrics and scripts referenced from postgres-metrics, cloudwatch, performance-insights, slow-query-observability, and wait-event-analysis -- this workflow organizes them, it does not redefine them.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_single_row_dashboard_snapshot.sql`](scripts/01_single_row_dashboard_snapshot.sql) -- Single-row, dashboard-panel-friendly snapshot of the handful of metrics most teams put on a 'cluster at a glance' stat panel.
2. [`scripts/02_baseline_dashboard_layout_recommendations.md`](scripts/02_baseline_dashboard_layout_recommendations.md) -- Proposed baseline panel layout for a Grafana/CloudWatch Aurora PostgreSQL DBA dashboard, grouped by operational question.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- A dashboard mixing CloudWatch (instance/cluster-level) and SQL-sourced (per-connection) panels should clearly label which instance (writer vs. a specific reader) each SQL-sourced panel reflects, since pg_stat_activity and most catalog views are per-instance, while several CloudWatch metrics (VolumeBytesUsed, AuroraReplicaLag) are cluster- or per-reader-scoped in ways that do not map one-to-one onto a single SQL connection.
- Panels sourced from cumulative PostgreSQL counters reset on an Aurora failover -- annotate the dashboard with failover events (available as a CloudWatch event) so a sudden drop in a rate panel immediately after a failover is not mistaken for an actual workload decrease.
- Aurora reader instances can be added or removed as part of normal autoscaling -- a dashboard's per-reader panels should be built to handle a changing instance count over time rather than assuming a fixed set of reader identifiers.

## 8. Interpretation Guide

- This is a starting layout, not a mandate -- adapt panel groupings to this cluster's actual failure history and the platform team's existing tooling conventions.
- Panels backed by cumulative PostgreSQL counters (throughput, cache hit ratio, WAL) need the dashboard tool to compute a rate/derivative between samples -- wiring the raw cumulative value directly into a stat panel without a rate calculation will show a number that only ever goes up.
- Panels backed by CloudWatch metrics are already rate/gauge-appropriate as published; panels backed by this repository's SQL scripts are point-in-time snapshots unless the collector polls them on an interval and the dashboard tool computes the rate itself.
- Group panels by operational question ('are we out of headroom', 'is replication healthy', 'is vacuum keeping up') rather than by source system (SQL vs. CloudWatch) -- an on-call engineer during an incident thinks in terms of the question, not the data source.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- This workflow is planning/documentation -- it has no immediate remediation of its own.

**Short-term remediation** (hours to days):

- Add the single-row snapshot query (script 01) as a quick stat-panel data source for any panel group not yet wired up individually, then replace it with the fuller per-panel queries as time allows.
- Close the single highest-value gap identified during the dashboard audit first (typically vacuum/XID visibility or replication lag, per the incident-history findings from database-health/comprehensive-health-check).

**Long-term engineering fix** (days to weeks):

- Standardize this dashboard layout across every cluster in the fleet via infrastructure-as-code (Grafana provisioning, or a shared CloudWatch dashboard template), so coverage does not depend on which team built which cluster's dashboard.
- Revisit the panel groupings periodically against the escalation criteria in each source workflow, since a threshold that made sense at last year's trading volume may no longer be the right line to draw.

## 10. Production Safety

- The one SQL script in this workflow is strictly read-only and inexpensive; safe to poll on a short interval from a dashboard collector.
- This workflow recommends dashboard structure only -- it does not itself grant any permission or provision any AWS resource; implementing it follows whatever change process the platform team already uses for dashboard/infrastructure-as-code changes.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- This workflow does not define escalation criteria of its own -- each panel group's escalation threshold is inherited from the workflow that owns that signal (see Related Issues and each panel's source workflow).

## 12. Related Issues

- [postgres-metrics](../postgres-metrics/README.md)
- [cloudwatch](../cloudwatch/README.md)
- [performance-insights](../performance-insights/README.md)
- [slow-query-observability](../slow-query-observability/README.md)
- [wait-event-analysis](../wait-event-analysis/README.md)
- [comprehensive-health-check](../../database-health/comprehensive-health-check/README.md)
- [daily-health-check](../../database-health/daily-health-check/README.md)
