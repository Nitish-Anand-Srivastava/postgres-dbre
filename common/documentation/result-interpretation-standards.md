# Result Interpretation Standards

Shared conventions used across `common/scripts/` output (and, where
adopted, across the rest of the repository) so results are read
consistently regardless of which script produced them.

## 1. Column naming

* Size columns are paired: a machine-sortable `*_bytes` (or `*_ms`, etc.)
  column alongside a human-readable `*_pretty` column, when both are
  useful. Sort/filter on the raw column; read the pretty column.
* Boolean columns are prefixed `is_` / `has_` / `allows_` so their meaning
  is unambiguous without consulting the script.
* Timestamps are reported in UTC and labeled accordingly
  (`check_time_utc`), avoiding session-timezone ambiguity when comparing
  output collected from different sessions or operators.

## 2. Nulls are informative, not just "no data"

Several Aurora-specific views return `NULL` in specific, documented
situations rather than as an error condition -- for example,
`aurora_replica_status().last_update_timestamp` is `NULL` for the row
representing the instance you are currently connected to (see
`06_aurora_replica_topology_and_lag.sql`). Treat an unexpected `NULL`
as a prompt to check the relevant script's `HOW TO INTERPRET RESULTS`
header field before assuming a data-collection failure.

## 3. No universal thresholds

None of the common scripts (nor the workflow scripts elsewhere in this
repository) hardcode a "good" vs. "bad" threshold for a metric, because
the right threshold depends on your workload. Where a script's guidance
mentions a number (e.g., "sustained lag over a few hundred milliseconds"),
treat it as a starting point for judgment, not a hard rule -- establish
your own baselines during normal operation and compare against those
during an investigation.

## 4. Comparing across instances

When a question requires comparing writer vs. reader, or reader vs.
reader, always identify the specific instance each result set came from
first (`05_instance_recovery_and_role_status.sql` /
`06_aurora_replica_topology_and_lag.sql`). Results collected through the
load-balancing reader endpoint without pinning to a specific instance
endpoint cannot be reliably compared against each other.

## Related reading

* `common/README.md` -- index of all common utilities.
* `docs/investigation-methodology/README.md` -- how interpretation fits
  into the broader investigation loop.
* `docs/glossary/README.md` -- terminology used in result column names
  and interpretation guidance.
