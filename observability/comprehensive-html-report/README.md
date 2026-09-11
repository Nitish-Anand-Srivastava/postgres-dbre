# Comprehensive Aurora PostgreSQL HTML Observability Report

**Category:** Observability | **Workflow:** `observability/comprehensive-html-report`

## 1. Problem Description

A production-validated, self-contained psql report that captures a broad Aurora PostgreSQL observability snapshot and writes structurally valid HTML for offline review. It combines configuration, sessions, waits, query statistics, vacuum, storage, replication, capacity, and extension readiness in one operator-friendly artifact while dynamically handling optional or unavailable Aurora features.

## 2. Typical Symptoms

- A DBA needs a broad point-in-time health and observability snapshot before narrowing into a symptom-specific workflow.
- An incident handoff or review needs a portable HTML artifact that can be opened without database access.
- A baseline, post-deployment, or periodic review needs configuration and runtime evidence captured together.

## 3. Business Impact

- A single report shortens initial triage by collecting related evidence consistently instead of relying on improvised queries.
- The portable HTML output supports incident handoffs and audit evidence without exposing database credentials or requiring recipients to connect to production.
- Dynamic feature detection prevents optional Aurora extensions or unsupported WAL paths from turning a broad diagnostic run into a partial report.

## 4. Possible Root Causes

- Not a single-failure workflow: it identifies potential pressure across configuration, sessions, queries, vacuum, storage, replication, and observability coverage.
- Findings are point-in-time indicators and must be compared with workload baselines and the focused workflows linked below before remediation.

## 5. Investigation Strategy

1. Confirm the target instance and connect using TLS with a least-privileged monitoring role.
2. Run the numbered report once with ON_ERROR_STOP enabled and explicit HTML output redirection as documented in scripts/README.md.
3. Open the generated HTML locally and start with the executive summary and prioritized findings.
4. Use the detailed sections to validate each finding, then continue in the relevant focused workflow before changing configuration or terminating sessions.

## 6. Prerequisites

- A supported psql client on Linux, macOS, or Windows; the report depends on psql meta-commands and is not intended for a generic SQL-only client.
- CONNECT on the target database plus pg_monitor, or equivalent SELECT privileges on the referenced system catalogs and statistics views.
- TLS connection settings for the Aurora endpoint. sslmode=verify-full with the current Amazon RDS CA bundle is recommended; sslmode=require encrypts traffic but does not verify server identity.
- No extension is mandatory. pg_stat_statements, pg_wait_sampling, apg_plan_mgmt, and version-specific catalog views are detected before use; auto_explain is correctly treated as a preload-only module.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_postgres_observability_report.sql`](scripts/01_postgres_observability_report.sql) -- Generates a self-contained HTML snapshot spanning Aurora PostgreSQL configuration, workload, waits, queries, maintenance, storage, replication, capacity, and observability readiness.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- This imported report is the current main-branch version of [`platforms/aurora-postgresql/aws-rds/postgres_observability_report.sql`](https://github.com/Nitish-Anand-Srivastava/database-reliability-engineering/blob/main/platforms/aurora-postgresql/aws-rds/postgres_observability_report.sql), production-validated against Aurora PostgreSQL 17.7 after Nitish-Anand-Srivastava/database-reliability-engineering#16.
- Aurora extensions are not assumed available. Extension and module checks distinguish installed extensions, unavailable extensions, and auto_explain's shared_preload_libraries-only activation model.
- Unsupported Aurora WAL statistics paths are guarded so the report records availability guidance rather than aborting.
- Settings with PostgreSQL unit suffixes are interpreted through catalog metadata rather than assuming every setting is a bare integer.

## 8. Interpretation Guide

- Start with the prioritized findings, but treat thresholds as prompts for investigation rather than automatic remediation decisions.
- Session, wait, and instance statistics describe the specific Aurora instance reached by the connection; a reader report does not substitute for a writer report when investigating writer load.
- Unavailable sections are explicitly reported when an extension or Aurora PostgreSQL path is unsupported; absence of that section's metrics is not evidence that the underlying workload is healthy.
- Keep the generated HTML only in an approved local evidence location because it can contain database names, role names, query text, schema names, and operational metadata. Generated reports are intentionally excluded from this repository.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Do not apply recommendations directly from the HTML report during an incident. Confirm the signal in the linked focused workflow and use its safety and escalation guidance.

**Short-term remediation** (hours to days):

- Compare findings with the cluster's normal baseline and open targeted follow-up work for confirmed configuration, vacuum, query, replication, or capacity issues.
- Re-run after approved changes to capture before-and-after evidence using the same target instance and monitoring role.

**Long-term engineering fix** (days to weeks):

- Schedule periodic runs only at a cadence appropriate for database size and retain reports under the organization's security and incident-evidence policy.
- Use recurring findings to improve continuous dashboards and alerts rather than relying on a comprehensive snapshot as the primary monitoring system.

## 10. Production Safety

- The report is LOW RISK WRITE, not READ ONLY: it creates and populates only one temporary table scoped to the psql session; it does not write application tables or persist database objects.
- The report reads many system catalogs and statistics views. Runtime is typically seconds to several minutes but scales with object count, statement statistics, and database size; avoid repeatedly running it during peak load.
- The report prints recommendations that may mention disruptive actions. Those strings are output only and are never executed by this script.
- Use -v ON_ERROR_STOP=1 so a failed section stops the run instead of producing a success-looking partial artifact.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Any critical finding that affects availability, transaction ID safety, replication, or connection headroom is confirmed by the corresponding focused workflow.
- The report cannot complete with the documented role because required catalog visibility is restricted; involve the database platform owner rather than broadening privileges ad hoc.
- Runtime or load is materially higher than the documented range; stop repeated runs and use narrower scripts while investigating the cause.

## 12. Related Issues

- [postgres-metrics](../postgres-metrics/README.md)
- [slow-query-observability](../slow-query-observability/README.md)
- [wait-event-analysis](../wait-event-analysis/README.md)
- [comprehensive-health-check](../../database-health/comprehensive-health-check/README.md)
- [autovacuum-not-keeping-up](../../vacuum-and-autovacuum/autovacuum-not-keeping-up/README.md)
- [replication-health](../../replication-and-ha/replication-health/README.md)
- [capacity-forecasting](../../storage-and-capacity/capacity-forecasting/README.md)
