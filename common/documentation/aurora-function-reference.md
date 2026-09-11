# Aurora Function Quick Reference

A quick reference for the Aurora PostgreSQL-specific functions used by
`common/scripts/`. This is a working subset, not a full reprint of AWS's
documentation; see the link at the bottom for the complete list.

| Function | Returns | Used in |
| --- | --- | --- |
| `aurora_version()` | Single text value -- the Aurora PostgreSQL engine version | `01_postgres_and_aurora_version.sql` |
| `aurora_db_instance_identifier()` | Single text value -- the DB instance identifier of the instance you are connected to | `05_instance_recovery_and_role_status.sql` |
| `aurora_replica_status()` | Set of rows, one per instance in the cluster (writer + readers), including lag and LSN information | `06_aurora_replica_topology_and_lag.sql` |

## Why these and not community PostgreSQL equivalents

* There is no community PostgreSQL equivalent for `aurora_version()` /
  `aurora_db_instance_identifier()` -- they only exist because Aurora's
  compute/storage separation makes "which instance, which engine build"
  a meaningful question distinct from `version()`.
* `aurora_replica_status()` is preferred over `pg_stat_replication` for
  reader lag because Aurora's readers do not maintain a traditional
  physical replication connection to the writer the way self-managed
  PostgreSQL streaming replicas do -- `pg_stat_replication` may return
  no rows, or rows with different semantics, on an Aurora writer. See
  `docs/aurora-postgresql/README.md` for the full comparison.

## A note on privileges

None of the functions above require any special role membership beyond
`CONNECT` on the target database -- they are intentionally accessible to
any authenticated session, which is why `common/scripts/` can state
`REQUIRED PRIVILEGES: None beyond CONNECT` for the scripts that use them.

## Related reading

* `docs/aurora-postgresql/README.md` -- full behavioral differences from
  community PostgreSQL, including a larger function table.
* AWS's [Aurora PostgreSQL functions reference](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Appendix.AuroraPostgreSQL.Functions.html)
  for the complete, authoritative list.
