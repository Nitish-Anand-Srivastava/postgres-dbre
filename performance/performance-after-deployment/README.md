# Performance Degradation After Deployment

**Category:** Performance Issues | **Workflow:** `performance/performance-after-deployment`

## 1. Problem Description

Database performance degraded shortly after an application or schema deployment. This workflow focuses specifically on deployment-correlated causes: new/changed queries, index changes, migration side effects, and connection/config changes shipped with the release.

## 2. Typical Symptoms

- Degradation onset closely follows a known deployment timestamp.
- A specific new feature/endpoint correlates with the new load pattern.
- A schema migration ran as part of the deployment (new column, new index, backfill).

## 3. Business Impact

- Deployment-correlated regressions are often the most preventable class of incident, and require both an immediate fix and a process improvement to avoid recurrence.

## 4. Possible Root Causes

- A new query pattern shipped without a supporting index.
- A migration that ran CREATE INDEX (non-concurrent) or ALTER TABLE, holding a stronger-than-expected lock during deployment.
- A CONCURRENTLY index build that failed partway through the deployment, leaving an invalid index.
- A connection pool/config change (new service instance count, changed pool size) increasing total connections beyond prior baseline.
- A backfill/data-migration job left running concurrently with production traffic.

## 5. Investigation Strategy

1. Confirm what changed: review the deployment's migration/DDL history.
2. Check for invalid indexes left behind by a failed CONCURRENTLY build during the deployment.
3. Check pg_stat_statements for new queryids with high total time that did not exist before the deployment.
4. Check current connection counts/pool composition against the pre-deployment baseline.
5. Check for any lingering backfill/migration session still running.

## 6. Prerequisites

- Deployment/migration change log with timestamps.
- pg_stat_statements extension created in the target database.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_invalid_indexes_since_deployment.sql`](scripts/01_invalid_indexes_since_deployment.sql) -- Checks for invalid indexes, the most common direct side effect of a deployment's failed CONCURRENTLY build.
2. [`scripts/02_new_expensive_queries.sql`](scripts/02_new_expensive_queries.sql) -- Surfaces the current top statements by total execution time, to identify any new queryid dominating since the deployment.
3. [`scripts/03_connection_profile_change.sql`](scripts/03_connection_profile_change.sql) -- Checks current connection composition by application_name, to detect a pool-size or service-count change shipped with the deployment.
4. [`scripts/04_lingering_migration_sessions.sql`](scripts/04_lingering_migration_sessions.sql) -- Checks for any long-running session that could be a still-active backfill/migration job from the deployment.

## 8. Interpretation Guide

- An invalid index discovered here that maps to a table touched by the deployment's migration is close to a confirmed root cause.
- A new queryid dominating pg_stat_statements immediately after the deployment window is the direct application-level regression to hand back to the deploying team with evidence.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If a failed CONCURRENTLY build left an invalid index, rebuild it per schema-changes/concurrent-index-build.
- If a lingering backfill session is found and confirmed non-critical to complete immediately, coordinate pausing/throttling it with the owning team.

**Short-term remediation** (hours to days):

- Ship a follow-up fix (index, query rewrite) for the new regressed query pattern.

**Long-term engineering fix** (days to weeks):

- Adopt pre-deployment and post-deployment checks (database-health/pre-deployment-check, post-deployment-check) as a standing part of the release process.
- Require CONCURRENTLY + post-build validation for all production index changes (see schema-changes/concurrent-index-build).

## 10. Production Safety

- Investigation scripts are read-only.
- Any corrective DDL must follow schema-changes guidance, never a same-day non-concurrent rebuild on a hot table.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- The deployment cannot be safely forward-fixed within the incident window -- escalate to the deploying team's leadership to authorize a rollback.

## 12. Related Issues

- [sudden-performance-degradation](../sudden-performance-degradation/README.md)
- [query-regression](../query-regression/README.md)
- [post-deployment-check](../../database-health/post-deployment-check/README.md)
- [failed-index-build](../../schema-changes/failed-index-build/README.md)
