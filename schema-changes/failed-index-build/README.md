# Failed Index Build Cleanup

**Category:** Schema Changes and DDL | **Workflow:** `schema-changes/failed-index-build`

## 1. Problem Description

An index build did not complete and left an INVALID index behind. This is the specific, expected aftermath of a cancelled or interrupted `CREATE INDEX CONCURRENTLY` (and of `REINDEX CONCURRENTLY`), and it is worse than it looks: the leftover index is completely invisible to the planner, so it provides zero query benefit, while still being fully maintained by every insert and update on the table and fully processed by every vacuum. It is strictly worse than having no index at all. This workflow finds these leftovers, establishes why the build failed so the retry does not repeat it, cleans them up safely, and confirms the table is back to a known-good state.

## 2. Typical Symptoms

- A concurrent index build was cancelled, timed out, deadlocked, or died with its session.
- An index exists in the catalog but the planner never uses it, and `EXPLAIN` shows a sequential scan where the index should apply.
- An index appears with `indisvalid = false` or `indisready = false` in the catalog.
- Write latency on a table increased after a failed build and never came back down.
- An Aurora failover occurred while an index build was running.
- Storage consumption rose by roughly the size of an index, but the expected query improvement never materialized.

## 3. Business Impact

- The leftover index costs write amplification, WAL volume, storage, and vacuum time on every operation against the table -- continuously, for as long as it exists -- while delivering nothing.
- The query the index was meant to fix is still slow, so the original performance problem is unresolved and still degrading with growth.
- Repeated retries without cleanup can leave multiple INVALID indexes stacked on the same table, multiplying the waste.
- On Aurora the storage the failed build consumed permanently raised the volume high-water mark, so even after cleanup the cost remains.

## 4. Possible Root Causes

- The build was cancelled manually because it was taking too long or causing reader lag.
- A `statement_timeout` set at session, role, or database level fired part-way through.
- The build session was disconnected -- a client timeout, a network interruption, a terminal closed.
- An Aurora failover or instance restart occurred mid-build, aborting it on the old writer.
- A unique index build found a duplicate key that violates the proposed uniqueness constraint.
- The build deadlocked with concurrent application traffic on the same table.
- The build exhausted local storage while spilling its sort, because `maintenance_work_mem` was too small for the table.
- A `REINDEX CONCURRENTLY` was interrupted, which leaves the same kind of leftover under a name suffixed `_ccnew`.

## 5. Investigation Strategy

1. Find every INVALID index in the database and size the waste they represent.
2. Check whether any build is still running -- an index that looks invalid may simply be a build that has not finished yet, and dropping it would be a serious mistake.
3. Establish why the build failed, using the timeout settings and the current lock picture, so the retry does not repeat it.
4. Drop the leftover safely through the runbook, using the concurrent drop form so the cleanup itself does not block anything.
5. Confirm the cleanup is complete and the table's index inventory is back to a known-good state before retrying the build.

## 6. Prerequisites

- `pg_monitor` for the investigation scripts; index or table ownership for the drop itself.
- Certainty that no build is currently in progress for the index you are about to drop -- confirmed via the progress view, not assumed.
- An understanding of why the original build failed, so the retry is not simply a repeat of the same attempt.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_invalid_indexes.sql`](scripts/01_invalid_indexes.sql) -- Finds every INVALID index in the database and quantifies the storage each one is wasting.
2. [`scripts/02_builds_currently_running.sql`](scripts/02_builds_currently_running.sql) -- Confirms whether any index build is still in progress, because an in-flight build legitimately appears invalid until it completes.
3. [`scripts/03_failure_context_and_settings.sql`](scripts/03_failure_context_and_settings.sql) -- Gathers the timeout settings and current lock picture that explain why the build failed, so the retry does not repeat it.
4. [`scripts/04_cleanup_invalid_index_runbook.md`](scripts/04_cleanup_invalid_index_runbook.md) -- The guarded DDL runbook for removing an INVALID index left by a failed build, with lock level, blocking risk, transaction behavior, and rollback documented.
5. [`scripts/05_verify_cleanup.sql`](scripts/05_verify_cleanup.sql) -- Confirms the leftover is gone and the target table's index inventory is back to a known-good state before any retry.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- An Aurora failover during an index build reliably leaves an INVALID index on the new writer. Make an invalid-index check part of your standard post-failover validation.
- Dropping an INVALID index frees its space for reuse inside the Aurora volume but does not reduce the billed high-water mark. The storage cost of the failed build is already permanent.
- Aurora readers see the same catalog as the writer, so an INVALID index is invisible to the planner on every instance -- there is no scenario where a reader benefits from a leftover the writer cannot use.
- `REINDEX CONCURRENTLY` leftovers named with a `_ccnew` suffix behave identically on Aurora and are cleaned up the same way.

## 8. Interpretation Guide

- `indisvalid = false` means the planner will never use the index. `indisready = false` means it is not even being maintained by writes yet. Both indicate an incomplete build; neither is recoverable by waiting.
- Before dropping anything, confirm via `pg_stat_progress_create_index` that no build is running. An index for an in-flight build legitimately shows as invalid until the build completes -- dropping it mid-build wastes hours of work and is the one genuinely destructive mistake available in this workflow.
- An index name ending in `_ccnew` (or `_ccnew1`, `_ccnew2`) is the signature of an interrupted `REINDEX CONCURRENTLY`. These are always safe to drop once no reindex is running, because the original index is still present and valid.
- Multiple INVALID indexes with similar definitions on the same table means the build has been retried repeatedly without cleanup. Drop all of them before the next attempt.
- `wasted_size` from the invalid index report is the storage being consumed for nothing. On Aurora, dropping the index frees it for reuse inside the volume but does not reduce billed storage, so the cost of the failed attempt is already sunk.
- If the build failed because of a duplicate key on a unique index, cleaning up the index is only half the job -- the duplicate data is a real data-integrity finding and needs the owning team involved before any retry.
- A failed build on a table that also shows high dead tuples is a compounding problem: the build blocked autovacuum while it ran, so cleanup plus a vacuum is usually the right sequence.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Confirm no build is in progress, then drop the INVALID index concurrently. This is one of the few remediations in the whole toolkit with essentially no downside -- the object being removed provides zero benefit by definition.

**Short-term remediation** (hours to days):

- Fix whatever caused the original failure before retrying: clear the long-running transactions, remove the `statement_timeout`, raise `maintenance_work_mem`, or resolve the duplicate key.
- Run a vacuum on the affected table if the failed build blocked autovacuum for a long period.
- Retry the build through the concurrent-index-build runbook, with the failure cause addressed.

**Long-term engineering fix** (days to weeks):

- Add an INVALID index check to routine health checks so leftovers are found within a day rather than discovered months later during a storage investigation.
- Standardize build sessions with `statement_timeout = 0` and a generous `maintenance_work_mem`, removing the two most common failure causes structurally.
- Check for INVALID indexes as part of post-failover validation, since a failover during a build reliably produces one.

## 10. Production Safety

- All `.sql` scripts here are read-only.
- The drop is documented in the `.md` runbook and must use `DROP INDEX CONCURRENTLY`, which takes only a `ShareUpdateExclusiveLock` and does not block application traffic.
- `DROP INDEX CONCURRENTLY` cannot run inside a transaction block -- the same restriction, and the same common failure, as the concurrent create.
- Never drop an index without first confirming through the progress view that no build is running against it. That is the one action in this workflow that can genuinely destroy work.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- The build failed because of a duplicate key violation on a unique index -- that is a data-integrity finding and needs the owning team before any retry.
- The same build has now failed three or more times for reasons that are not understood -- stop retrying and investigate the root cause properly.
- INVALID indexes are appearing without anyone having run a build, which suggests repeated failovers or instance instability and needs an AWS support case.
- The leftover is on a table where the write overhead is measurably affecting the trading path and the owning team is not available to authorize the drop.

## 12. Related Issues

- [concurrent-index-build](../concurrent-index-build/README.md)
- [safe-index-creation](../safe-index-creation/README.md)
- [drop-index-safely](../drop-index-safely/README.md)
- [invalid-indexes](../../tables-and-indexes/invalid-indexes/README.md)
- [index-growth](../../storage-and-capacity/index-growth/README.md)
- [index-bloat](../../vacuum-and-autovacuum/index-bloat/README.md)
