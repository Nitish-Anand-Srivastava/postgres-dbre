"""Authoritative expected workflow catalog for the Aurora PostgreSQL DBA
Toolkit repository.

This mirrors the categories and workflow directories explicitly enumerated
in the repository's design specification. It is used by
``validate_repo.py`` to report catalog completeness -- i.e. which expected
workflow directories exist and which are still outstanding.

Two kinds of categories are tracked:

* ``EXPLICIT_CATALOG`` -- categories for which the specification lists an
  exact set of expected workflow subdirectories. Missing entries are
  reported as outstanding work.
* ``OPEN_CATALOG`` -- categories the specification names as top-level
  directories but does not enumerate a fixed workflow list for
  (``security-and-access``, ``maintenance``, ``disaster-recovery``). These
  are only checked for existence and for having at least one populated
  workflow; no fixed subdirectory list is enforced.

This module intentionally contains no logic beyond plain data so it can be
reviewed/updated independently of the validation script itself.
"""
from __future__ import annotations

EXPLICIT_CATALOG: dict[str, list[str]] = {
    "performance": [
        "high-cpu",
        "high-database-load",
        "slow-queries",
        "query-regression",
        "high-iops",
        "high-latency",
        "throughput-degradation",
        "sudden-performance-degradation",
        "performance-after-deployment",
        "performance-after-failover",
    ],
    "concurrency-and-locking": [
        "blocked-queries",
        "lock-contention",
        "deadlocks",
        "long-running-transactions",
        "idle-in-transaction",
        "transaction-contention",
        "ddl-blocking",
        "connection-contention",
    ],
    "transactions-and-xid": [
        "xid-wraparound-risk",
        "transaction-age",
        "oldest-transactions",
        "prepared-transactions",
        "multixact-risk",
    ],
    "vacuum-and-autovacuum": [
        "autovacuum-not-keeping-up",
        "vacuum-progress",
        "dead-tuples",
        "table-bloat",
        "index-bloat",
        "vacuum-blocked",
        "emergency-autovacuum",
        "analyze-statistics",
    ],
    "partitioning": [
        "investigate-partitioning-candidate",
        "partition-existing-large-table",
        "partition-maintenance",
        "partition-pruning",
        "missing-partitions",
        "partition-skew",
        "partition-performance",
    ],
    "archival-and-data-lifecycle": [
        "investigate-archiving-candidate",
        "archive-large-table",
        "archive-partition",
        "purge-old-data",
        "retention-policy",
        "archive-validation",
    ],
    "tables-and-indexes": [
        "unused-indexes",
        "duplicate-indexes",
        "missing-index-candidates",
        "sequential-scan-investigation",
        "index-bloat",
        "table-bloat",
        "invalid-indexes",
        "large-tables",
        "rapidly-growing-tables",
        "table-access-patterns",
    ],
    "connections": [
        "connection-exhaustion",
        "connection-spikes",
        "idle-connections",
        "idle-in-transaction",
        "connection-pooling",
        "max-connections-planning",
        "application-connection-analysis",
    ],
    "replication-and-ha": [
        "replication-lag",
        "reader-performance",
        "reader-lag-investigation",
        "failover-investigation",
        "failover-readiness",
        "writer-reader-imbalance",
        "replication-health",
    ],
    "database-health": [
        "comprehensive-health-check",
        "daily-health-check",
        "pre-deployment-check",
        "post-deployment-check",
        "pre-maintenance-check",
        "post-maintenance-check",
        "capacity-health-check",
    ],
    "query-optimization": [
        "analyze-query-plan",
        "nested-loop-problems",
        "hash-join-analysis",
        "merge-join-analysis",
        "cardinality-estimation",
        "stale-statistics",
        "sort-spills",
        "temp-file-investigation",
        "inefficient-index-usage",
        "query-plan-regression",
    ],
    "storage-and-capacity": [
        "database-growth",
        "table-growth",
        "index-growth",
        "wal-generation",
        "temp-file-growth",
        "capacity-forecasting",
        "unexpected-storage-growth",
    ],
    "schema-changes": [
        "safe-index-creation",
        "concurrent-index-build",
        "failed-index-build",
        "large-table-ddl",
        "column-type-change",
        "add-column-large-table",
        "add-index-large-table",
        "drop-index-safely",
        "ddl-lock-investigation",
    ],
    "incident-response": [
        "database-unavailable",
        "sudden-latency-spike",
        "high-cpu",
        "connection-exhaustion",
        "lock-storm",
        "runaway-query",
        "application-timeouts",
        "post-deployment-incident",
        "production-triage",
    ],
    "observability": [
        "postgres-metrics",
        "performance-insights",
        "cloudwatch",
        "slow-query-observability",
        "wait-event-analysis",
        "dashboard-recommendations",
    ],
    "automation": [
        "health-checks",
        "growth-monitoring",
        "xid-monitoring",
        "index-monitoring",
        "capacity-monitoring",
    ],
}

OPEN_CATALOG: list[str] = [
    "security-and-access",
    "maintenance",
    "disaster-recovery",
]

# Directories at repository root that are NOT operational category
# directories and must be skipped by category/workflow discovery.
NON_CATEGORY_ROOT_DIRS = {
    "docs",
    "common",
    "tools",
    ".github",
    ".git",
}

ALL_EXPECTED_CATEGORIES = sorted(set(EXPLICIT_CATALOG) | set(OPEN_CATALOG))
