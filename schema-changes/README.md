# Schema Changes

Safe patterns for making DDL changes -- adding/altering columns, building or
dropping indexes, changing column types -- against production tables without
an unplanned outage. The governing idea across this whole category is that
on a live, high-traffic database the *lock* is almost always the real risk,
not the work itself: an operation that takes an `AccessExclusiveLock` for
even a fraction of a second can queue every subsequent query against the
table behind it (see `concurrency-and-locking/ddl-blocking`), while the same
logical change done with the right statement form and the right off-peak
timing can be effectively invisible to production traffic.

Every read-only investigation script here is safe to run at any time. Every
actual DDL statement (`CREATE INDEX CONCURRENTLY`, `ALTER TABLE`, `DROP
INDEX CONCURRENTLY`, etc.) is presented as a guarded markdown runbook with a
worked, concrete example adapted from a real catalog-discovered candidate,
never an unresolved stand-in command, because the exact columns/table
involved are always an operator decision that cannot be safely defaulted.

## Workflows

| Workflow | Summary |
| --- | --- |
| [`safe-index-creation`](safe-index-creation/README.md) | Entry point for the index-creation family: whether an index is genuinely needed, and always via `CREATE INDEX CONCURRENTLY`, never a plain blocking `CREATE INDEX`. |
| [`concurrent-index-build`](concurrent-index-build/README.md) | The two-pass mechanics of `CREATE INDEX CONCURRENTLY`, why a cancelled build leaves an `INVALID` index, and how to monitor progress via `pg_stat_progress_create_index`. |
| [`failed-index-build`](failed-index-build/README.md) | Recovery workflow for an `INVALID` index left behind by a failed/cancelled concurrent build. |
| [`large-table-ddl`](large-table-ddl/README.md) | Strategy for any DDL against a very large, hot table -- why the lock, not the work, is the risk. |
| [`column-type-change`](column-type-change/README.md) | When `ALTER TABLE ... ALTER COLUMN ... TYPE` requires a full table rewrite and `AccessExclusiveLock`, and when a compatible change avoids it. |
| [`add-column-large-table`](add-column-large-table/README.md) | The safe pattern for adding a column to a large table without a blocking rewrite. |
| [`add-index-large-table`](add-index-large-table/README.md) | Index creation specifically sized for very large tables: build-time expectations, disk headroom, and off-peak scheduling. |
| [`drop-index-safely`](drop-index-safely/README.md) | Safe index removal -- never a hard drop without first confirming genuine disuse. |
| [`ddl-lock-investigation`](ddl-lock-investigation/README.md) | Investigating a DDL statement stuck waiting on a lock, and how to safely resolve it. |

## Related categories

* [`concurrency-and-locking/ddl-blocking`](../concurrency-and-locking/ddl-blocking/README.md) -- the symptom this category's `ddl-lock-investigation` resolves.
* [`tables-and-indexes/unused-indexes`](../tables-and-indexes/unused-indexes/README.md) -- unused/invalid/bloated index findings that motivate `drop-index-safely` and `failed-index-build`.
* [`maintenance/reindex-strategy`](../maintenance/reindex-strategy/README.md) -- builds on this category's single-index build guidance for multi-index campaigns.
* [`incident-response/post-deployment-incident`](../incident-response/post-deployment-incident/README.md) -- cross-links here when a schema change is implicated in an incident.
