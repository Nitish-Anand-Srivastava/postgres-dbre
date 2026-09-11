# 04_wait_event_type_reference

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `04_wait_event_type_reference.md` |
| Purpose | Reference guide to each wait_event_type category's meaning, typical causes, and whether it is normally actionable. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Any instance (writer or reader) |
| Safety | READ ONLY (reference documentation only; no SQL statements are executed by this file) |
| Expected impact | None -- this is reference/planning documentation, not an executable script. Any AWS-side action it describes (enabling a feature, creating an alarm) is called out explicitly and is a change-managed action outside this repository's SQL scope. |
| Required privileges | Role membership in `pg_monitor` (or `pg_read_all_stats`) is sufficient. No superuser required. |
| Prerequisites | None to read this reference. |
| Execution order | Step 04 of workflow `observability/wait-event-analysis` |
| Related scripts | ../performance-insights/README.md |

## How to interpret / use this runbook

Use this table to quickly classify whether a wait_event_type found in scripts 01-03 is expected background noise or requires immediate investigation, without needing to look it up externally during an incident.

---

## Wait event type reference

| `wait_event_type` | Meaning | Typically actionable? |
| --- | --- | --- |
| `Lock` | Waiting for a heavyweight lock (row/table/object) held by another session. | Yes, always -- investigate the blocking session immediately via `concurrency-and-locking/blocked-queries`. |
| `LWLock` | Waiting on an internal lightweight lock protecting a PostgreSQL data structure (e.g. buffer mapping, WAL insertion). | Occasional/brief: no. Sustained concentration: yes -- indicates internal contention, often on a very hot buffer or WAL insertion point. |
| `BufferPin` | Waiting for an exclusive pin on a shared buffer, usually held briefly by another backend reading/modifying the same page. | Occasional/brief: no. Sustained: investigate what is holding the buffer pinned for an unusually long time. |
| `Activity` | A background process (checkpointer, autovacuum launcher, walwriter, logical replication launcher) waiting for its next scheduled activity. | No -- this is the expected idle state for these processes. |
| `Client` | Waiting on the client application -- the query result has been sent, or the connection is simply idle. | No -- this is the expected state for a pooled, idle connection. |
| `Extension` | Waiting inside code registered by an extension (e.g. `pg_stat_statements` itself, or another installed extension). | Depends on the extension; investigate only if concentrated and unexpected. |
| `IPC` | Inter-process communication -- commonly parallel query workers synchronizing, or waiting on a checkpoint/vacuum coordination point. | Usually no (self-resolving); sustained large counts warrant checking what parallel/maintenance operations are in flight. |
| `IO` | Waiting on a storage read or write. On Aurora, this is a round trip to the distributed storage layer, not local disk. | Yes, if sustained -- corresponds to elevated CloudWatch `DiskQueueDepth`/`VolumeReadIOPs`/`VolumeWriteIOPs`. |
| `Timeout` | The process is in a deliberate sleep (e.g. `pg_sleep()`, or a background worker's configured interval). | No, unless the specific `wait_event` value is unexpected for this workload. |

## Cross-reference with Performance Insights

Performance Insights colors its DB load stacked chart using this exact same
`wait_event_type` taxonomy (see `performance-insights`), so a wait-event
finding from a live query here should match the coloring seen in the PI
console for the same time window -- if PI shows a different classification
for what appears to be the same moment, re-check the exact instance and
time zone/window being compared.

## When a wait_event value is not in this table

New wait events are occasionally added between PostgreSQL minor/major
versions. Query `pg_wait_events` directly (joined automatically by scripts
01 and 03 in this workflow) for the authoritative, version-current
description rather than relying on this table alone if a value looks
unfamiliar.
