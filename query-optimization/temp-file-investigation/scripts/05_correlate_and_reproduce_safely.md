# 05_correlate_and_reproduce_safely

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `05_correlate_and_reproduce_safely.md` |
| Purpose | Guarded runbook for correlating temporary files with statements via the logs and reproducing a spill safely. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Reader instance preferred for reproduction; the parameter and role changes apply cluster-wide. |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | Steps 1 and 2: no database impact (a parameter change and log reading). Step 3: a full execution of the statement including its temporary file I/O. Step 4: changes the default settings for new sessions of the named role. |
| Required privileges | pg_monitor for investigation; CloudWatch Logs read access for step 2; ALTER ROLE privileges for step 4; parameter-group change permissions for step 1. |
| Prerequisites | Scripts 01-04 completed and a candidate statement identified. |
| Execution order | Step 05 of workflow `query-optimization/temp-file-investigation` |
| Related scripts | ../sort-spills/README.md, ../hash-join-analysis/README.md |

## How to interpret / use this runbook

Use the log to get the real parameter values, the reader to reproduce safely, and the plan to classify the spill as a sort, a hash, an aggregate, or a materialization -- then continue in the workflow named in the classification table. The role-scoped settings in step 4 are containment while the real fix is built, not the fix itself.

---

## Where the definitive evidence lives

The catalog views tell you that spilling happened and, with pg_stat_statements,
which normalized statement did it. They cannot tell you **when**, with which
parameters, or how large each individual spill was. That information is in the
PostgreSQL log, which on Aurora is exported to CloudWatch Logs.

## Step 1 -- Turn on temp file logging (if it is off)

`log_temp_files` is a DB cluster parameter group setting on Aurora. Setting it to
`0` logs every temporary file with its size and the statement that created it, and
takes effect without a reboot.

```
log_temp_files = 0        -- log every temporary file, any size
```

The cost is one log line per temporary file. On a cluster spilling heavily that is
a lot of lines -- which is itself the signal you are looking for.

## Step 2 -- Find the spills in CloudWatch Logs

The log group is `/aws/rds/cluster/<cluster-id>/postgresql`. A CloudWatch Logs
Insights query such as:

```
fields @timestamp, @message
| filter @message like /temporary file/
| sort @timestamp desc
| limit 200
```

returns lines of the form:

```
LOG:  temporary file: path "base/pgsql_tmp/pgsql_tmp12345.0", size 412319744
STATEMENT:  SELECT ... ORDER BY executed_at DESC OFFSET 900000 LIMIT 50
```

The `STATEMENT` line carries the **real parameter values**, which pg_stat_statements
normalizes away. That is what makes the log the definitive source: it tells you
which account, which market, or which date range actually caused the spill.

## Step 3 -- Reproduce safely, on a reader

```sql
-- On a READER instance, using the real parameters taken from the log.
SET LOCAL statement_timeout = '30s';
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT ... ;
```

This executes the statement and produces the same spill again -- on the reader,
where the local storage I/O does not compete with order matching. Read the plan to
classify the spill:

| Plan evidence | Spill type | Workflow to follow |
|---|---|---|
| `Sort Method: external merge  Disk:` | Sort spill | `sort-spills` |
| `Hash ... Batches: N` where N > 1 | Hash join spill | `hash-join-analysis` |
| `HashAggregate ... Disk Usage:` | Hash aggregate spill | `hash-join-analysis` (same memory rules) |
| `CTE Scan` over a large materialized CTE | Materialization | Rewrite the CTE or add `NOT MATERIALIZED` |

Do not reproduce a data-modifying statement without `BEGIN ... ROLLBACK`, and do not
reproduce anything against wallet, ledger, or settlement tables during trading
hours.

## Step 4 -- Bound the damage while the real fix is built

```sql
-- Make a runaway analytical query fail instead of consuming all local storage.
-- Applies to new sessions for that role; agree it with the workload owner first,
-- because the query will now error rather than merely run slowly.
ALTER ROLE reporting_role SET temp_file_limit = '8GB';

-- Give the analytical role the memory it actually needs, sized with the
-- sort-spills or hash-join-analysis runbook -- not guessed.
ALTER ROLE reporting_role SET work_mem = '256MB';
```

Both are role-scoped: the exchange's order-path role keeps its original, safe
settings.

## Never do this

- Do not raise `work_mem` globally to make temp file volume disappear. It converts
  a disk problem into a memory-exhaustion risk across every connection.
- Do not set `temp_file_limit` on the order-path role without agreement: a trading
  query that fails is worse than a trading query that spills.
- Do not reproduce a large spilling statement on the writer during trading hours
  when a reader is available.
