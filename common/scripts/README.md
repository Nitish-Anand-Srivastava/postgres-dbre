# Common Scripts

Execution order, safety classification, and expected runtime for the
environment/triage utilities in `common/scripts/`. Unlike issue workflows,
these scripts have no fixed dependency order -- run whichever one answers
your current question -- but the numbering reflects a sensible default
sequence for "I just opened a session, what am I looking at."

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_postgres_and_aurora_version.sql` | Reports PostgreSQL and Aurora engine version. | READ ONLY | Low (sub-second) |
| 02 | `02_current_role_and_privileges.sql` | Reports current role attributes and predefined-role membership. | READ ONLY | Low (sub-second) |
| 03 | `03_installed_extensions.sql` | Lists installed and available-but-not-installed extensions. | READ ONLY | Low (sub-second) |
| 04 | `04_database_and_cluster_inventory.sql` | Lists every non-template database and its size/connection limit. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_instance_recovery_and_role_status.sql` | Confirms writer vs. reader status of the connected instance. | READ ONLY | Low (sub-second) |
| 06 | `06_aurora_replica_topology_and_lag.sql` | Reports every cluster instance and current replica lag. | READ ONLY | Low (sub-second) |
| 07 | `07_key_monitoring_settings.sql` | Reports key parameters that other workflows depend on. | READ ONLY | Low (sub-second) |
| 08 | `08_environment_summary.sql` | One-row "where and who am I" session/instance summary. | READ ONLY | Low (sub-second) |

## Execution order

There is no required order among these scripts -- each is independently
useful and self-contained. As a default habit, run 01, 02, and 08 first
when opening a new session against an unfamiliar cluster; run 05 and 06
specifically before comparing writer vs. reader behavior.

## Required permissions

Every script here requires only `CONNECT` on the target database. None
require `pg_monitor` or elevated roles, though a couple of columns (in
`02_current_role_and_privileges.sql`) become more informative with broader
role membership. See `docs/permissions/README.md` for the full model.

## Expected output

Every script returns a single small result set (one row, or a handful of
rows) intended to be read directly. There is no companion `.md` guidance
file needed beyond each script's own header, since none of these scripts
require follow-up interpretation beyond what is documented there.

## When to stop and escalate

These are informational utilities, not incident workflows -- they never
produce a reason to escalate by themselves. If any of them errors instead
of returning a result (for example, `01_postgres_and_aurora_version.sql`
failing because `aurora_version()` does not exist), that indicates you are
connected to something other than the intended Aurora PostgreSQL cluster;
resolve the connection target before proceeding with any workflow.

## Scripts that should not be run during severe incidents

None. All scripts in `common/scripts/` are read-only, parameter-free, and
safe to run at any time, including during a severe incident, without prior
coordination.
