"""Workflow definitions: automation/ category (5 issue directories).

This category is the "how do the read-only investigation workflows in the
rest of this toolkit get run on a schedule, unattended" answer. Every
workflow here is deliberately split into two kinds of content:

* Read-only `.sql` scripts that check whether the relevant scheduling/
  tracking infrastructure (pg_cron, or an optional dba_toolkit.* tracking
  table) is already deployed, and report on it if so. These never create,
  schedule, or install anything -- they are safe to run unmodified at any
  time, exactly like every other script in this repository.
* `.md` runbooks that document the actual deployment steps (CREATE SCHEMA/
  CREATE TABLE DDL, a pg_cron `cron.schedule()` call, or an external-
  scheduler alternative) as a deliberate, change-managed action a human
  reads and runs once -- never an auto-executing script.

`pg_cron` itself is never installed by anything in this repository: adding
it to `shared_preload_libraries` on the Aurora cluster parameter group
requires a reboot, and running `CREATE EXTENSION pg_cron;` is a
change-managed administrative action documented in
docs/prerequisites/README.md, not a step any script here performs
automatically. Every script that depends on pg_cron or on an optional
dba_toolkit.* tracking table detects its absence and prints an
instructional notice instead of failing.

automation/growth-monitoring is the authoritative home for the
dba_toolkit.table_size_history collector that
tables-and-indexes/rapidly-growing-tables and
sql_blocks.table_growth_rate_from_snapshot() already reference and depend
on for a genuine growth-rate calculation.
"""
from __future__ import annotations

from typing import List

from . import sql_blocks as sb
from .helpers import (
    PG_MONITOR,
    PG_MONITOR_PLUS_PGSS,
    WRITER_ONLY,
    WRITER_PREFERRED,
    md_script,
    sql_script,
)
from .model import Workflow

CATEGORY_SLUG = "automation"
CATEGORY_TITLE = "Automation"


def _wf(**kwargs) -> Workflow:
    kwargs.setdefault("category_slug", CATEGORY_SLUG)
    kwargs.setdefault("category_title", CATEGORY_TITLE)
    return Workflow(**kwargs)


def _pg_cron_guarded(available_body: str, unavailable_notice: str) -> str:
    """Wrap a pg_cron-dependent query body in an extension-presence guard.

    This never creates the extension itself -- it only detects whether
    `pg_cron` is already installed in the current database, and prints an
    instructional notice instead of failing with "schema cron does not
    exist" when it is not. `unavailable_notice` must not contain a literal
    apostrophe or a double-hyphen sequence (SQL string-literal content, not
    a `--` comment).
    """
    return (
        "-- pg_cron presence check. This script never creates or schedules\n"
        "-- anything -- it only detects whether pg_cron is already installed\n"
        "-- in this database.\n"
        "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') AS pg_cron_available\n"
        "\\gset\n"
        "\n"
        "\\if :pg_cron_available\n"
        f"{available_body}\n"
        "\\else\n"
        f"SELECT '{unavailable_notice}' AS notice;\n"
        "\\endif"
    )


def _tracking_table_guarded(tracking_table: str, available_body: str, unavailable_notice: str) -> str:
    """Wrap a query against an optional dba_toolkit.* tracking table in a
    to_regclass() existence guard, matching the pattern used throughout
    sql_blocks.py (see table_growth_rate_from_snapshot()). Never creates the
    table itself.
    """
    return (
        f"\\set tracking_table '{tracking_table}'\n"
        "SELECT to_regclass(:'tracking_table') IS NOT NULL AS tracking_table_exists\n"
        "\\gset\n"
        "\n"
        "\\if :tracking_table_exists\n"
        f"{available_body}\n"
        "\\else\n"
        f"SELECT :'tracking_table' || '{unavailable_notice}' AS notice;\n"
        "\\endif"
    )


PG_CRON_PREREQ = (
    "`pg_cron` must already be installed in this database. It must first be added to "
    "`shared_preload_libraries` on the Aurora DB cluster parameter group (requires a "
    "reboot to take effect), and then `CREATE EXTENSION pg_cron;` must be run once by "
    "an administrator in a change-managed session. This script never creates or "
    "schedules anything -- it only detects whether pg_cron is already installed, and "
    "prints an instructional notice instead of failing if it is not."
)

TRACKING_TABLE_NOTE = (
    "This is optional infrastructure this workflow is responsible for deploying, not a "
    "built-in catalog. This script detects its absence via to_regclass() and prints an "
    "instructional notice instead of failing when it has not been deployed yet."
)

WORKFLOWS: List[Workflow] = []

# ---------------------------------------------------------------------------
# health-checks
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="health-checks",
    title="Scheduling Routine Health Checks",
    summary=(
        "Documents how to run the database-health/ workflows (daily-health-check, "
        "comprehensive-health-check, capacity-health-check, and the pre/post-deployment "
        "and pre/post-maintenance checks) on a recurring, unattended schedule instead of "
        "manually and inconsistently. Two scheduling mechanisms are covered: `pg_cron` "
        "running inside the database when it is enabled on the cluster parameter group, "
        "and an external scheduler (an AWS Lambda function on an EventBridge/CloudWatch "
        "Events cron rule, invoking the database via the RDS Data API or a network path "
        "to the writer) when it is not. This workflow itself performs no scheduling -- it "
        "is diagnostic (does pg_cron already have jobs registered) and documentary (how to "
        "add more), never an auto-executing setup step."
    ),
    symptoms=[
        "Health checks are only ever run manually, inconsistently, and usually only after something has already gone wrong.",
        "A recent incident review found that a health-check finding (rising XID age, a growing unused index, a capacity threshold) had been true for weeks before anyone happened to look.",
        "A capacity or database-health workflow's remediation-long-term section recommends 'run this on a schedule' with no existing schedule in place.",
    ],
    business_impact=[
        "An unscheduled health check is only as good as someone remembering to run it -- on a 24/7 exchange platform, the gap between 'this would have been caught' and 'this was actually caught' is where slow-burning incidents (XID age, storage growth, capacity exhaustion) turn into outages.",
        "Consistent scheduled health checks produce a comparable historical record (did this get worse since last week), which a one-off manual run never can.",
    ],
    root_causes=["N/A -- this is a scheduling/automation workflow, not an incident investigation."],
    investigation_strategy=[
        "Check whether `pg_cron` is already installed and, if so, what jobs (if any) are already registered.",
        "If `pg_cron` has registered jobs, review their recent run history for failures before assuming the schedule is working.",
        "If `pg_cron` is not installed or not appropriate for this cluster, use the external-scheduler pattern documented in this workflow's runbook instead.",
    ],
    prerequisites=[
        "`pg_monitor` role membership (or `pg_read_all_stats`) for the read-only checks in this workflow.",
        PG_CRON_PREREQ + " Only required for scripts 01-02; the external-scheduler path in script 03 has no such dependency.",
    ],
    interpretation_guide=[
        "A database with no `pg_cron` jobs registered and no external scheduler in place is not automatically broken -- it simply means every database-health workflow is currently run manually. Treat that as the starting point to fix, not as an error.",
        "A registered `pg_cron` job with a recent run history full of failures is worse than no job at all -- it creates false confidence that a check is happening when it is not. Always review script 02's output before trusting that a schedule is working.",
        "Prefer `pg_cron` for checks that only need to run inside the database and whose output can be logged to a table pg_cron itself can write to; prefer the external-scheduler pattern when the check's output needs to reach an external alerting system (PagerDuty, Slack, CloudWatch alarms) directly.",
    ],
    remediation_immediate=["N/A -- this workflow is diagnostic and documentary; no action is taken automatically."],
    remediation_short_term=["Schedule the highest-value health check (typically daily-health-check or capacity-health-check) first, following the runbook in this workflow, before attempting to schedule every workflow in the repository at once."],
    remediation_long_term=[
        "Schedule every relevant database-health/ workflow on a documented cadence (daily for daily-health-check, weekly or monthly for the heavier comprehensive-health-check and capacity-health-check).",
        "Route health-check findings into the same alerting/ticketing system used for other operational alerts, so a health-check finding gets the same visibility as a paging incident.",
    ],
    production_safety=[
        "Every `.sql` script in this workflow is strictly read-only.",
        "The runbook in script 03 documents scheduling steps for the operator to review and apply deliberately -- it is markdown, not an executable script, and is never auto-run by anything in this repository.",
        "Adding `pg_cron` to `shared_preload_libraries` requires an Aurora instance reboot -- always schedule that change through the same change-management process as any other cluster parameter group change.",
    ],
    escalation_criteria=["A scheduled health check has been silently failing (per script 02) for long enough that its findings could not have been acted on -- treat any finding from the next successful run with extra scrutiny and review why the failures went unnoticed."],
    related_issues=[
        "../growth-monitoring/README.md",
        "../capacity-monitoring/README.md",
        "../../database-health/daily-health-check/README.md",
        "../../database-health/comprehensive-health-check/README.md",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_pg_cron_extension_and_jobs",
        "Checks whether pg_cron is installed in this database and, if so, lists every job currently registered.",
        _pg_cron_guarded(
            """SELECT
    jobid,
    schedule,
    command,
    nodename,
    nodeport,
    database,
    username,
    active
FROM cron.job
ORDER BY jobid;""",
            "pg_cron is not installed in this database, so no scheduled jobs are "
            "registered here. See the scheduling runbook in this workflow (script "
            "04) for how to enable it via the Aurora cluster parameter group, or "
            "how to use an external scheduler instead if pg_cron is not "
            "appropriate for this cluster.",
        ),
        "An empty result set with pg_cron installed means the extension is available but nothing has been scheduled yet. Each row's schedule is a standard five-field cron expression evaluated in the database server's time zone; cross-reference command against the runbooks this workflow and growth-monitoring/xid-monitoring/index-monitoring/capacity-monitoring document to confirm a job actually matches what you expect it to run.",
        prerequisites=PG_CRON_PREREQ,
        related_scripts="02_pg_cron_recent_job_run_history.sql",
        table_purpose="Registered pg_cron jobs, if the extension is installed.",
    ),
    sql_script(
        "02", "02_pg_cron_recent_job_run_history",
        "Checks whether pg_cron is installed and, if so, reports the most recent run outcome for every registered job.",
        _pg_cron_guarded(
            """\\set lookback_hours 72
SELECT
    r.jobid,
    j.schedule,
    r.status,
    r.return_message,
    r.start_time,
    r.end_time,
    r.end_time - r.start_time AS duration
FROM cron.job_run_details r
LEFT JOIN cron.job j ON j.jobid = r.jobid
WHERE r.start_time > now() - make_interval(hours => :lookback_hours)
ORDER BY r.start_time DESC;""",
            "pg_cron is not installed in this database, so no job run history "
            "is available. See the scheduling runbook in this workflow (script "
            "04) for how to enable it, or how to use an external scheduler "
            "instead.",
        ),
        "A status of failed, or a return_message describing an error, means the schedule exists but the check is not actually running successfully -- this is worse than having no schedule at all, because it creates false confidence. Review failures immediately; a job that has failed on every run since it was created has never actually protected anything.",
        prerequisites=PG_CRON_PREREQ,
        related_scripts="03_quick_health_signal.sql",
        table_purpose="Recent pg_cron job run outcomes, if the extension is installed.",
    ),
    sql_script(
        "03", "03_quick_health_signal",
        "The single lightweight, read-only health signal a scheduled job should capture on every run: instance role, connection headroom, and transaction ID age.",
        sb.cluster_recovery_role() + "\n\n" + sb.max_connections_headroom() + "\n\n" + sb.database_transaction_age(),
        "This is the deliberately small subset of database-health/comprehensive-health-check that is cheap enough to run every few minutes unattended: it answers 'am I talking to the writer', 'are we close to the connection ceiling', and 'is XID age climbing'. Alert on pct_utilized above roughly 80% sustained across consecutive runs and on pct_of_freeze_max_age above 40-50%; treat is_reader_instance = true on what the scheduler believes is the writer endpoint as an immediate signal that a failover has occurred (see replication-and-ha/failover-investigation). Anything this script flags is a trigger to run the full comprehensive-health-check workflow, not a diagnosis on its own.",
        execution_location=WRITER_PREFERRED,
        related_scripts="04_scheduling_runbook.md, ../../database-health/comprehensive-health-check/README.md",
        table_purpose="Quick unattended health signal: role, connection headroom, XID age.",
    ),
    md_script(
        "04", "04_scheduling_runbook",
        "Documents how to schedule the database-health/ workflows on a recurring basis, via pg_cron where it is enabled or an external scheduler where it is not.",
        (
            "## Option A: pg_cron (requires it to already be enabled)\n\n"
            "`pg_cron` runs scheduled jobs *inside* the database server process, on the database "
            "server's clock, as the role that scheduled the job. It cannot execute host-level "
            "commands or reach external systems (Slack, PagerDuty, CloudWatch) directly -- it can "
            "only run SQL. This makes it a good fit for checks whose output is fine to leave in a "
            "results-log table for a human or a separate poller to review, and a poor fit for "
            "anything that must page someone directly.\n\n"
            "**Enabling pg_cron (a one-time, change-managed prerequisite, not something this "
            "workflow does for you):**\n\n"
            "1. Add `pg_cron` to `shared_preload_libraries` on the Aurora DB cluster parameter "
            "group. This requires an instance reboot to take effect -- schedule it through your "
            "normal change-management process, the same as any other parameter group change that "
            "needs a reboot.\n"
            "2. After the reboot, have an administrator run `CREATE EXTENSION pg_cron;` once, in a "
            "change-managed session, in the database designated to host the `cron` schema (Aurora "
            "typically requires this to be the `postgres` database; jobs can still target other "
            "databases on the same cluster via the `database` argument to `cron.schedule()`).\n"
            "3. Confirm it is available with script 01 in this workflow before scheduling anything.\n\n"
            "**Scheduling a health check once pg_cron is available:**\n\n"
            "```sql\n"
            "-- Runs daily-health-check's read-only scripts every morning at 06:00 UTC and\n"
            "-- logs a simple completion marker. In practice you would adapt this to invoke\n"
            "-- your actual daily-health-check queries (or a wrapper function you have written\n"
            "-- that runs them and stores structured results) rather than a bare marker insert.\n"
            "SELECT cron.schedule(\n"
            "    'daily_health_check',\n"
            "    '0 6 * * *',\n"
            "    $$INSERT INTO dba_toolkit.health_check_log (checked_at, workflow) "
            "VALUES (now(), 'daily-health-check')$$\n"
            ");\n"
            "```\n\n"
            "Review the job afterward with script 01 (is it registered) and script 02 (is it "
            "actually succeeding) in this workflow -- a scheduled job that silently fails every "
            "run is worse than no schedule at all.\n\n"
            "To remove a job later: `SELECT cron.unschedule('daily_health_check');`\n\n"
            "## Option B: external scheduler (no pg_cron dependency)\n\n"
            "When `pg_cron` is not enabled, or when a check's result needs to reach an external "
            "alerting system directly, schedule it outside the database instead:\n\n"
            "- An AWS Lambda function on an Amazon EventBridge (CloudWatch Events) scheduled rule, "
            "connecting to the writer endpoint (directly, or via the RDS Data API for a "
            "Data-API-enabled Aurora Serverless cluster) to run the health-check queries and "
            "publish a CloudWatch custom metric or post to an existing alerting channel on failure.\n"
            "- A scheduled ECS Fargate task or a CI/CD scheduled pipeline running `psql` against the "
            "cluster with a read-only monitoring role, piping output to your existing log "
            "aggregation and alerting stack.\n\n"
            "Either external option needs the exact same read-only database role (`pg_monitor` "
            "membership, `CONNECT` on the target database) that every script in this repository "
            "already documents -- no additional database privilege is required to schedule a "
            "check externally.\n\n"
            "## Which database-health workflows to schedule, and how often\n\n"
            "- `daily-health-check`: daily, off-peak, e.g. early morning UTC.\n"
            "- `comprehensive-health-check` and `capacity-health-check`: weekly or monthly -- they "
            "are heavier and intended for a periodic deep review, not a daily loop.\n"
            "- `pre-deployment-check` / `post-deployment-check` and `pre-maintenance-check` / "
            "`post-maintenance-check`: triggered by the deployment/maintenance pipeline itself, "
            "not a fixed schedule -- wire them into the pipeline rather than a cron expression.\n"
        ),
        "This is a documentation runbook, not an executable script -- read the option that matches whether pg_cron is enabled on this cluster, adapt the illustrative SQL/Lambda outline to your actual health-check queries and alerting destination, and apply it deliberately rather than piping any part of this file into psql as-is.",
        related_scripts="../growth-monitoring/README.md, ../../database-health/daily-health-check/README.md",
        table_purpose="Scheduling runbook for database-health workflows (pg_cron or external scheduler).",
    ),
]

# ---------------------------------------------------------------------------
# growth-monitoring
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="growth-monitoring",
    title="Table Growth History Collector",
    summary=(
        "This is the authoritative home for the optional dba_toolkit.table_size_history "
        "tracking table that tables-and-indexes/rapidly-growing-tables and "
        "storage-and-capacity's growth/forecasting workflows already reference and depend "
        "on for a genuine growth-rate calculation -- every one of them detects this table's "
        "absence via to_regclass() and points back here. Without it, every growth-related "
        "workflow in this toolkit can only report a single point-in-time size, never an "
        "actual rate. This workflow documents the collector's schema, its periodic "
        "population job, and provides read-only scripts to confirm it is deployed and "
        "collecting on a healthy cadence."
    ),
    symptoms=[
        "A growth or capacity-forecasting workflow's script reports that dba_toolkit.table_size_history does not exist.",
        "Capacity planning is currently limited to single-point-in-time size snapshots with no way to compute an actual growth rate.",
        "The collector was deployed at some point but nobody has confirmed it is still running.",
    ],
    business_impact=[
        "Every day this collector is not deployed is a day of trend data that cannot be reconstructed retroactively -- the earlier it is deployed, the sooner every growth/capacity-forecasting workflow in this toolkit becomes genuinely useful instead of limited to point-in-time snapshots.",
        "A collector that silently stops running (a dropped pg_cron job, a failed scheduled task) produces the same 'no history available' outcome as never having deployed it, but is far more likely to go unnoticed because the table still exists.",
    ],
    root_causes=["N/A -- this is an infrastructure-deployment and monitoring workflow, not an incident investigation."],
    investigation_strategy=[
        "Check whether the tracking table already exists and, if so, how many rows it has and when it was last populated.",
        "If it exists, check for gaps in the collection cadence -- a table that exists but stopped being populated months ago is effectively the same problem as one that was never deployed.",
        "If it does not exist, or has an unhealthy cadence, deploy or repair the collector using the runbook in this workflow.",
    ],
    prerequisites=[
        "`pg_monitor` role membership (or `pg_read_all_stats`) for the read-only status checks.",
        "For deployment: a role with `CREATE` privilege on the target database (to create the `dba_toolkit` schema and table) and, if scheduling via pg_cron, the prerequisites in automation/health-checks.",
    ],
    interpretation_guide=[
        "A tracking_table_exists = false result from script 01 is not a failure of this workflow -- it is the expected state before the collector has ever been deployed. Proceed to the runbook in script 04.",
        "A tracking table that exists but whose latest_capture_at is far in the past (days, for a collector intended to run hourly or daily) means the collector has stopped running -- check the scheduling mechanism (pg_cron job status via automation/health-checks, or the external scheduler's own logs) rather than assuming the table itself needs fixing.",
        "distinct_tables_tracked growing over time as new tables are created is expected and healthy; a sudden drop suggests the collector's population query is filtering more narrowly than intended (e.g. a schema exclusion that now excludes a schema it should not).",
    ],
    remediation_immediate=["N/A -- this workflow is diagnostic and documentary. If the collector has stopped running, its scheduling mechanism (pg_cron job, external scheduled task) is the thing to repair, not this workflow itself."],
    remediation_short_term=["Deploy the collector following the runbook in this workflow if it does not exist yet, so the earliest possible baseline snapshot is captured today rather than after further delay."],
    remediation_long_term=[
        "Add a retention/pruning policy to the collector's own scheduled job (delete rows older than a documented retention window, e.g. 13 months) so the tracking table itself does not become an unbounded-growth problem.",
        "Monitor the collector's own pg_cron job run history (see automation/health-checks) so a silently-stopped collector is caught quickly rather than discovered the next time someone needs a growth rate.",
    ],
    production_safety=[
        "The two `.sql` scripts in this workflow are strictly read-only.",
        "The deployment runbook (script 04) contains DDL and a scheduled INSERT job -- it is markdown, deliberately never an auto-executing script, and must be reviewed and applied by an operator.",
        "The collector's own periodic INSERT is lightweight (one row per tracked relation per collection interval) and its read query (`pg_total_relation_size()` per relation) is the same catalog-only read every other sizing script in this toolkit already performs.",
    ],
    escalation_criteria=["The collector has been down (no new rows) for long enough that a business-critical capacity decision cannot be made from trend data -- treat the immediate priority as restoring collection, and fall back to storage-and-capacity's single-point-in-time scripts for the decision at hand."],
    related_issues=[
        "../health-checks/README.md",
        "../xid-monitoring/README.md",
        "../../tables-and-indexes/rapidly-growing-tables/README.md",
        "../../storage-and-capacity/table-growth/README.md",
        "../../storage-and-capacity/capacity-forecasting/README.md",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_check_tracking_table_status",
        "Checks whether dba_toolkit.table_size_history already exists and, if so, reports its row count and capture window.",
        _tracking_table_guarded(
            "dba_toolkit.table_size_history",
            """SELECT
    count(*)                                     AS total_rows,
    count(DISTINCT (schema_name, table_name))     AS distinct_tables_tracked,
    min(captured_at)                              AS earliest_capture_at,
    max(captured_at)                              AS latest_capture_at,
    now() - max(captured_at)                      AS time_since_latest_capture
FROM dba_toolkit.table_size_history;""",
            " does not exist in this database yet. See the deployment runbook "
            "in this workflow (script 04) to create it and schedule its "
            "periodic collector. Every growth/capacity-forecasting script in "
            "this toolkit that depends on it will continue to work today, "
            "printing the same notice, until it is deployed.",
        ),
        "A healthy, actively-collecting deployment shows time_since_latest_capture well within one collection interval (for an hourly job, well under an hour; for a daily job, well under a day). A large time_since_latest_capture on an existing table means the collector's schedule has stopped running -- check its pg_cron job status (automation/health-checks) or external scheduler logs, not this table.",
        prerequisites=TRACKING_TABLE_NOTE,
        related_scripts="02_verify_collection_cadence.sql",
        table_purpose="Tracking table existence, row count, and capture window.",
    ),
    sql_script(
        "02", "02_verify_collection_cadence",
        "Where the tracking table exists, checks for gaps between consecutive capture timestamps to confirm the collector is running on a healthy, consistent cadence.",
        _tracking_table_guarded(
            "dba_toolkit.table_size_history",
            """\\set lookback_days 30
WITH captures AS (
    SELECT DISTINCT captured_at
    FROM dba_toolkit.table_size_history
    WHERE captured_at > now() - make_interval(days => :lookback_days)
),
gaps AS (
    SELECT
        captured_at,
        lag(captured_at) OVER (ORDER BY captured_at)                       AS previous_capture_at,
        captured_at - lag(captured_at) OVER (ORDER BY captured_at)          AS gap_since_previous
    FROM captures
)
SELECT
    previous_capture_at,
    captured_at,
    gap_since_previous
FROM gaps
WHERE gap_since_previous IS NOT NULL
ORDER BY gap_since_previous DESC
LIMIT 20;""",
            " does not exist in this database yet, so no collection cadence "
            "can be verified. See the deployment runbook in this workflow "
            "(script 04).",
        ),
        "This lists the largest gaps between consecutive collection runs over the lookback window, largest first. A consistent cadence shows every gap close to the intended collection interval (e.g. 1 hour). A gap much larger than the intended interval means the collector missed one or more scheduled runs during that window -- correlate the timing against the pg_cron job run history (automation/health-checks) or the external scheduler's own logs to find why.",
        prerequisites=TRACKING_TABLE_NOTE,
        related_scripts="03_growth_rate_from_history.sql",
        table_purpose="Gaps between consecutive collection timestamps, largest first.",
    ),
    sql_script(
        "03", "03_growth_rate_from_history",
        "The payoff query: computes actual per-table growth over the retention window from the collected history, which is the whole reason the collector exists.",
        sb.table_growth_rate_from_snapshot(),
        "This is the same block every growth/capacity workflow in this toolkit calls (sql_blocks.table_growth_rate_from_snapshot()), run here against the collector this workflow owns. Rank by growth_over_window, not by end_size_bytes: a moderately sized ledger or trade-fills table doubling every month is a nearer-term capacity and archival problem than a much larger but flat reference table. Feed the fastest-growing tables into archival-and-data-lifecycle/archive-large-table and into partitioning planning. If this prints the instructional notice instead of rows, the collector has not been deployed yet (script 04) or has collected fewer than two samples inside the lookback window.",
        related_scripts="04_deploy_collector_runbook.md, ../../tables-and-indexes/large-tables/README.md, ../../archival-and-data-lifecycle/archive-large-table/README.md",
        table_purpose="Per-table growth between the earliest and latest sample in the window.",
    ),
    md_script(
        "04", "04_deploy_collector_runbook",
        "Documents the exact DDL for dba_toolkit.table_size_history and the periodic collector job that populates it -- deliberate, reviewed infrastructure you deploy once, not something to pipe into psql unread.",
        (
            "Read this runbook in full before running anything in it. It creates a new schema and "
            "table, and schedules a recurring job that writes to it. None of it runs automatically "
            "as part of this repository -- you are choosing to deploy this collector.\n\n"
            "## 1. Create the schema and tracking table\n\n"
            "```sql\n"
            "CREATE SCHEMA IF NOT EXISTS dba_toolkit;\n\n"
            "CREATE TABLE dba_toolkit.table_size_history (\n"
            "    captured_at   timestamptz NOT NULL DEFAULT now(),\n"
            "    schema_name   text        NOT NULL,\n"
            "    table_name    text        NOT NULL,\n"
            "    size_bytes    bigint      NOT NULL,\n"
            "    PRIMARY KEY (captured_at, schema_name, table_name)\n"
            ");\n\n"
            "CREATE INDEX table_size_history_lookup\n"
            "    ON dba_toolkit.table_size_history (schema_name, table_name, captured_at);\n"
            "```\n\n"
            "The column names (`captured_at`, `schema_name`, `table_name`, `size_bytes`) are exact "
            "and load-bearing: sql_blocks.table_growth_rate_from_snapshot() and every script in "
            "tables-and-indexes/rapidly-growing-tables and storage-and-capacity that reads this "
            "table expect these names precisely. Do not rename them.\n\n"
            "## 2. The population query\n\n"
            "This single INSERT is what a scheduled job runs on every collection interval. It "
            "records the current total size (heap plus indexes plus TOAST) of every ordinary and "
            "partitioned table in every non-system schema:\n\n"
            "```sql\n"
            "INSERT INTO dba_toolkit.table_size_history (captured_at, schema_name, table_name, size_bytes)\n"
            "SELECT\n"
            "    now(),\n"
            "    n.nspname,\n"
            "    c.relname,\n"
            "    pg_total_relation_size(c.oid)\n"
            "FROM pg_class c\n"
            "JOIN pg_namespace n ON n.oid = c.relnamespace\n"
            "WHERE c.relkind IN ('r', 'p', 'm')\n"
            "  AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'dba_toolkit');\n"
            "```\n\n"
            "## 3. Schedule it -- Option A: pg_cron\n\n"
            "See automation/health-checks for the full pg_cron enablement prerequisites (parameter "
            "group change plus a reboot, then a change-managed `CREATE EXTENSION pg_cron;`). Once "
            "available:\n\n"
            "```sql\n"
            "SELECT cron.schedule(\n"
            "    'dba_toolkit_table_size_history_collector',\n"
            "    '0 * * * *',\n"
            "    $$INSERT INTO dba_toolkit.table_size_history (captured_at, schema_name, table_name, size_bytes)\n"
            "      SELECT now(), n.nspname, c.relname, pg_total_relation_size(c.oid)\n"
            "      FROM pg_class c\n"
            "      JOIN pg_namespace n ON n.oid = c.relnamespace\n"
            "      WHERE c.relkind IN ('r', 'p', 'm')\n"
            "        AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'dba_toolkit')$$\n"
            ");\n"
            "```\n\n"
            "An hourly schedule (`0 * * * *`) is a reasonable default; a daily schedule "
            "(`0 2 * * *`) is sufficient for most capacity-planning purposes and produces a much "
            "smaller table over time -- pick the cadence that matches how quickly the growth "
            "questions you ask actually need to be answered.\n\n"
            "## 3. Schedule it -- Option B: external scheduler\n\n"
            "If pg_cron is not enabled on this cluster, run the same population query from an "
            "EventBridge-scheduled Lambda function or a scheduled ECS/Fargate task connecting to "
            "the writer endpoint, using the same read/write role that owns the `dba_toolkit` "
            "schema. No additional privilege beyond `INSERT` on this one table is required.\n\n"
            "## 4. Retention -- prune the history table itself\n\n"
            "The collector table will itself grow forever without a retention policy. Add a "
            "second scheduled step (via the same pg_cron job or a second one, or the equivalent "
            "step in an external scheduler) to prune old rows on a documented retention window, "
            "for example:\n\n"
            "```sql\n"
            "DELETE FROM dba_toolkit.table_size_history\n"
            "WHERE captured_at < now() - interval '13 months';\n"
            "```\n\n"
            "Thirteen months keeps a full year of history available for year-over-year growth "
            "comparisons even a month after the retention boundary passes; adjust to your own "
            "capacity-review cadence.\n\n"
            "## 5. Confirm it is working\n\n"
            "Run script 01 in this workflow immediately after deployment to confirm the table "
            "exists, and again after at least two collection intervals have elapsed to confirm "
            "rows are actually accumulating. Run script 02 after at least a week to confirm the "
            "collection cadence is healthy, and script 03 to read the growth rates the collector "
            "now makes computable.\n"
        ),
        "This is infrastructure you deploy deliberately, not a script to run unread. Follow the numbered steps in order, adapt the schedule and retention window to your own operational cadence, and verify with scripts 01 and 02 afterward.",
        related_scripts="01_check_tracking_table_status.sql, ../../tables-and-indexes/rapidly-growing-tables/README.md, ../../storage-and-capacity/table-growth/README.md",
        table_purpose="Collector deployment runbook: schema, table DDL, population query, and scheduling.",
    ),
]

# ---------------------------------------------------------------------------
# xid-monitoring
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="xid-monitoring",
    title="Scheduled Transaction ID Age Monitoring",
    summary=(
        "The automated, scheduled counterpart to "
        "transactions-and-xid/transaction-age's manual database- and table-level XID age "
        "snapshots. Transaction ID wraparound risk is exactly the kind of slow-burning "
        "problem that a manual, occasionally-remembered check will eventually miss -- this "
        "workflow documents running the same read-only age checks on a recurring schedule "
        "with alert thresholds set well below the emergency failsafe, so a climbing trend "
        "is caught weeks before it becomes urgent."
    ),
    symptoms=[
        "transactions-and-xid/transaction-age has been run manually more than once and the team wants it scheduled instead.",
        "A prior XID wraparound risk incident's retrospective recommended automated monitoring as a long-term fix.",
        "No one can currently answer 'is our XID age trend improving or worsening' without running a manual check right now.",
    ],
    business_impact=[
        "Transaction ID wraparound, if it is ever allowed to reach the enforced limit, forces PostgreSQL to refuse new writes entirely -- a full outage. Scheduled monitoring with a conservative alert threshold is what keeps this a routine autovacuum-tuning conversation instead of an emergency.",
        "A climbing XID age trend is actionable weeks in advance if caught early (tune autovacuum, address a holding-back long-running transaction) but requires an emergency, high-risk manual VACUUM (FREEZE) if caught only at the failsafe threshold.",
    ],
    root_causes=["N/A -- this is a scheduling/automation workflow. See transactions-and-xid/xid-wraparound-risk for root-cause analysis once a scheduled check reports an elevated age."],
    investigation_strategy=[
        "Confirm the current database- and table-level XID age as the baseline (the same checks as transactions-and-xid/transaction-age).",
        "Schedule these checks to run and be recorded on a recurring cadence, per this workflow's runbook.",
        "Set an alert threshold well below the emergency failsafe (commonly 40-50% of autovacuum_freeze_max_age) so there is real lead time to act.",
    ],
    prerequisites=[
        "`pg_monitor` role membership (or `pg_read_all_stats`) for the read-only age-check scripts.",
        PG_CRON_PREREQ + " Only required if scheduling via pg_cron; the external-scheduler alternative in the runbook has no such dependency.",
    ],
    interpretation_guide=[
        "Track pct_of_freeze_max_age as a trend over successive scheduled runs, not just its current value -- a slowly climbing trend is actionable long before any single snapshot looks alarming, and a scheduled history is what makes the trend visible at all.",
        "Any scheduled run reporting age above roughly 75% of autovacuum_freeze_max_age should escalate immediately to transactions-and-xid/xid-wraparound-risk rather than waiting for the next scheduled run.",
    ],
    remediation_immediate=["N/A -- this workflow is scheduling/automation. Any single elevated finding should be escalated directly to transactions-and-xid/transaction-age or transactions-and-xid/xid-wraparound-risk."],
    remediation_short_term=["Deploy the scheduled checks in this workflow's runbook if they are not already running, using a conservative alert threshold from day one."],
    remediation_long_term=["Feed the scheduled history into the same dashboard/alerting stack used for other operational monitoring, so a climbing XID age trend gets the same visibility as any other capacity or health signal."],
    production_safety=[
        "The read-only age-check scripts in this workflow are identical in safety profile to transactions-and-xid/transaction-age's scripts -- strictly read-only, safe at any time.",
        "The scheduling runbook documents a pg_cron job or external scheduler invocation -- markdown, never auto-executed by this repository.",
    ],
    escalation_criteria=["A scheduled run reports database or table age above 75% of autovacuum_freeze_max_age -- escalate immediately to transactions-and-xid/xid-wraparound-risk regardless of when the next scheduled run would otherwise occur."],
    related_issues=[
        "../growth-monitoring/README.md",
        "../../transactions-and-xid/transaction-age/README.md",
        "../../transactions-and-xid/xid-wraparound-risk/README.md",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_database_age_snapshot",
        "Database-level XID age snapshot, intended to be captured on every scheduled run.",
        sb.database_transaction_age(),
        "Record pct_of_freeze_max_age from every scheduled run so a trend is visible over time, not just a single current value. Alert when it crosses your organization's chosen proactive threshold (commonly 40-50%).",
        related_scripts="02_table_age_snapshot.sql",
        table_purpose="Database-level XID age, for scheduled capture.",
    ),
    sql_script(
        "02", "02_table_age_snapshot",
        "Table-level XID age snapshot (top N oldest tables), intended to be captured on every scheduled run.",
        sb.table_transaction_age_top_n(),
        "Track which specific tables consistently rank highest across scheduled runs -- they are the highest-churn/least-frequently-vacuumed tables and the best candidates for proactive per-table freeze tuning, exactly as in transactions-and-xid/transaction-age.",
        related_scripts="03_scheduling_runbook.md",
        table_purpose="Table-level XID age, for scheduled capture.",
    ),
    md_script(
        "03", "03_scheduling_runbook",
        "Documents how to run the XID age snapshot scripts on a recurring schedule, with a recommended alert threshold, via pg_cron or an external scheduler.",
        (
            "## Recommended cadence and threshold\n\n"
            "Run both age-snapshot scripts at least daily; hourly is reasonable on a very "
            "high-write cluster where age can climb quickly. Alert at 40-50% of "
            "`autovacuum_freeze_max_age` -- this leaves weeks of lead time before the 75% "
            "threshold that transactions-and-xid/transaction-age treats as an escalation "
            "trigger, and far more before the emergency failsafe.\n\n"
            "## Option A: pg_cron\n\n"
            "See automation/health-checks for the full pg_cron enablement prerequisites. Once "
            "available, schedule a wrapper that records the result into a small history table "
            "rather than only ever reading the live value, so a trend is visible:\n\n"
            "```sql\n"
            "CREATE TABLE IF NOT EXISTS dba_toolkit.xid_age_history (\n"
            "    captured_at              timestamptz NOT NULL DEFAULT now(),\n"
            "    datname                  text        NOT NULL,\n"
            "    xid_age                  bigint      NOT NULL,\n"
            "    pct_of_freeze_max_age    numeric     NOT NULL,\n"
            "    PRIMARY KEY (captured_at, datname)\n"
            ");\n\n"
            "SELECT cron.schedule(\n"
            "    'dba_toolkit_xid_age_collector',\n"
            "    '0 * * * *',\n"
            "    $$INSERT INTO dba_toolkit.xid_age_history (captured_at, datname, xid_age, pct_of_freeze_max_age)\n"
            "      SELECT\n"
            "          now(),\n"
            "          datname,\n"
            "          age(datfrozenxid),\n"
            "          round(100.0 * age(datfrozenxid) /\n"
            "              (SELECT setting::numeric FROM pg_settings WHERE name = 'autovacuum_freeze_max_age'), 2)\n"
            "      FROM pg_database\n"
            "      WHERE datallowconn$$\n"
            ");\n"
            "```\n\n"
            "Add a threshold check as a second scheduled job (or an external alerting rule "
            "reading this table) that fires when `pct_of_freeze_max_age` exceeds your chosen "
            "threshold for any row.\n\n"
            "## Option B: external scheduler\n\n"
            "Where pg_cron is not enabled, run the same two age-snapshot queries from an "
            "EventBridge-scheduled Lambda or a scheduled task using the standard read-only "
            "`pg_monitor` role, and publish `pct_of_freeze_max_age` as a CloudWatch custom metric "
            "with an alarm at your chosen threshold -- this is often preferable here specifically "
            "because it lets the alarm page directly, without needing a separate poller on the "
            "`dba_toolkit.xid_age_history` table.\n\n"
            "## Retention\n\n"
            "Prune `dba_toolkit.xid_age_history` on the same kind of documented retention window "
            "as `dba_toolkit.table_size_history` in automation/growth-monitoring (a year or so is "
            "typically more than enough for this narrow, low-cardinality table).\n"
        ),
        "This is a documentation runbook, not an executable script -- adapt the illustrative DDL/scheduling SQL to your own threshold and alerting destination before applying it.",
        related_scripts="../growth-monitoring/README.md, ../../transactions-and-xid/transaction-age/README.md",
        table_purpose="Scheduling runbook for XID age monitoring (pg_cron or external scheduler).",
    ),
]

# ---------------------------------------------------------------------------
# index-monitoring
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="index-monitoring",
    title="Scheduled Index Health Monitoring",
    summary=(
        "The automated, scheduled counterpart to tables-and-indexes/unused-indexes and "
        "tables-and-indexes/invalid-indexes -- and to storage-and-capacity/index-growth's "
        "usage-context review. Index accretion (indexes added one at a time to fix "
        "individual slow queries, never reviewed as a set) is a slow, easy-to-miss trend; "
        "this workflow documents capturing unused, invalid, and usage/size context on a "
        "recurring schedule so the trend is visible before an ad-hoc cleanup project is the "
        "only option left."
    ),
    symptoms=[
        "tables-and-indexes/unused-indexes or tables-and-indexes/invalid-indexes has been run manually more than once with recurring findings, and the team wants it scheduled instead.",
        "storage-and-capacity/index-growth found that index accretion is an ongoing, not one-off, problem.",
        "An index cleanup project keeps needing to be redone from scratch because there is no standing record of what was already reviewed.",
    ],
    business_impact=[
        "Every unreviewed unused or invalid index is recurring, compounding cost -- storage, write amplification, and vacuum time -- that a one-off cleanup only resets rather than prevents from recurring.",
        "A recurring, recorded index-health check turns index hygiene into a standing, low-effort operational practice instead of an occasional large project.",
    ],
    root_causes=["N/A -- this is a scheduling/automation workflow. See tables-and-indexes/unused-indexes, tables-and-indexes/invalid-indexes, and storage-and-capacity/index-growth for root-cause analysis and remediation of any specific finding."],
    investigation_strategy=[
        "Capture unused-index, invalid-index, and index usage/size context snapshots as the baseline.",
        "Schedule these captures to run and be recorded on a recurring (typically weekly or monthly) cadence.",
        "Review the recorded history periodically, rather than only reacting to a single point-in-time run.",
    ],
    prerequisites=[
        "`pg_monitor` role membership (or `pg_read_all_stats`) for the read-only scripts in this workflow.",
        PG_CRON_PREREQ + " Only required if scheduling via pg_cron; the external-scheduler alternative in the runbook has no such dependency.",
    ],
    interpretation_guide=[
        "A single scheduled run's findings should be treated exactly as tables-and-indexes/unused-indexes and tables-and-indexes/invalid-indexes already document -- idx_scan resets on restart/failover, so never act on one run's zero-scan result alone; confirm persistence across multiple scheduled runs spanning at least one full business cycle first.",
        "An index appearing as an unused-index candidate across many consecutive scheduled runs, with no restart/failover in between, is much stronger evidence than a single manual check happening to catch it once.",
    ],
    remediation_immediate=["N/A -- this workflow is scheduling/automation. Any specific finding is remediated through tables-and-indexes/unused-indexes, tables-and-indexes/invalid-indexes, or tables-and-indexes/duplicate-indexes."],
    remediation_short_term=["Deploy the scheduled captures in this workflow's runbook if they are not already running."],
    remediation_long_term=["Review the recorded index-health history on a standing cadence (e.g. quarterly) as an input to a routine index cleanup pass, rather than only after a storage or performance problem prompts an ad-hoc review."],
    production_safety=[
        "Every `.sql` script in this workflow is strictly read-only, identical in safety profile to the tables-and-indexes/storage-and-capacity scripts it schedules.",
        "The scheduling runbook documents a pg_cron job or external scheduler invocation -- markdown, never auto-executed by this repository. No index is ever dropped or rebuilt by anything in this workflow.",
    ],
    escalation_criteria=["A scheduled run finds a newly-INVALID index on a core trading-path table -- treat this the same as tables-and-indexes/invalid-indexes recommends, since it indicates a recent failed concurrent build that may warrant investigation in its own right."],
    related_issues=[
        "../growth-monitoring/README.md",
        "../../tables-and-indexes/unused-indexes/README.md",
        "../../tables-and-indexes/invalid-indexes/README.md",
        "../../storage-and-capacity/index-growth/README.md",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_unused_indexes_snapshot",
        "Unused-index candidate snapshot, intended to be captured on every scheduled run.",
        sb.unused_indexes(),
        "Never act on a single scheduled run's result alone -- idx_scan resets on restart/failover, so confirm persistence across multiple scheduled runs spanning at least one full business cycle (including month-end/quarter-end batch jobs) before treating a candidate as confirmed-unused, exactly as tables-and-indexes/unused-indexes documents.",
        related_scripts="02_invalid_indexes_snapshot.sql",
        table_purpose="Unused-index candidates, for scheduled capture.",
    ),
    sql_script(
        "02", "02_invalid_indexes_snapshot",
        "INVALID-index snapshot, intended to be captured on every scheduled run so a failed concurrent build is caught promptly rather than discovered incidentally.",
        sb.invalid_indexes(),
        "Any row here found on a scheduled run that was empty on the previous run means a concurrent index or REINDEX build failed since then -- correlate the timing against recent deployment/migration activity and route to tables-and-indexes/invalid-indexes for the safe drop-and-rebuild remediation.",
        related_scripts="03_index_usage_and_size_snapshot.sql",
        table_purpose="INVALID indexes, for scheduled capture.",
    ),
    sql_script(
        "03", "03_index_usage_and_size_snapshot",
        "Index size, scan-count, and last-used snapshot, intended to be captured on every scheduled run to track index-growth and usage trends over time.",
        sb.index_bloat_and_usage(),
        "Recorded over successive scheduled runs, this is what actually shows an index-growth trend (storage-and-capacity/index-growth) rather than a single size figure -- an index whose size is climbing release over release with a flat or falling idx_scan is a much stronger over-indexing signal than either fact alone.",
        related_scripts="04_duplicate_indexes_snapshot.sql",
        table_purpose="Index size and usage, for scheduled capture.",
    ),
    sql_script(
        "04", "04_duplicate_indexes_snapshot",
        "Redundant/duplicate index snapshot, intended to be captured on every scheduled run so indexes added by successive migrations that duplicate an existing one are caught early.",
        sb.duplicate_indexes(),
        "Duplicates accumulate silently: two migrations, months apart, each add an index on the same leading column of an orders or trades table and nothing fails -- the cluster just pays for both on every write. A row that appears here for the first time on a scheduled run almost always traces to the most recent migration; review it against that change before it becomes permanent. Confirm the pair is genuinely redundant (identical column list, order, opclass, and predicate) via tables-and-indexes/duplicate-indexes before dropping either one.",
        related_scripts="05_scheduling_runbook.md",
        table_purpose="Duplicate/redundant index candidates, for scheduled capture.",
    ),
    md_script(
        "05", "05_scheduling_runbook",
        "Documents how to run the index-health snapshot scripts on a recurring schedule via pg_cron or an external scheduler.",
        (
            "## Recommended cadence\n\n"
            "Weekly or monthly is typically sufficient -- index usage and growth trends develop "
            "over weeks, not hours, so there is little value in a tighter cadence than for "
            "storage-and-capacity's other scheduled checks.\n\n"
            "## Option A: pg_cron\n\n"
            "See automation/health-checks for the full pg_cron enablement prerequisites. Once "
            "available, record results into a history table rather than only reading the live "
            "value, so a trend is visible:\n\n"
            "```sql\n"
            "CREATE TABLE IF NOT EXISTS dba_toolkit.index_health_history (\n"
            "    captured_at    timestamptz NOT NULL DEFAULT now(),\n"
            "    schema_name    text        NOT NULL,\n"
            "    table_name     text        NOT NULL,\n"
            "    index_name     text        NOT NULL,\n"
            "    index_size_bytes bigint    NOT NULL,\n"
            "    idx_scan       bigint,\n"
            "    is_valid       boolean     NOT NULL,\n"
            "    PRIMARY KEY (captured_at, schema_name, index_name)\n"
            ");\n\n"
            "SELECT cron.schedule(\n"
            "    'dba_toolkit_index_health_collector',\n"
            "    '0 3 * * 0',\n"
            "    $$INSERT INTO dba_toolkit.index_health_history\n"
            "          (captured_at, schema_name, table_name, index_name, index_size_bytes, idx_scan, is_valid)\n"
            "      SELECT\n"
            "          now(), n.nspname, c.relname, i.relname,\n"
            "          pg_relation_size(i.oid), s.idx_scan, ix.indisvalid\n"
            "      FROM pg_index ix\n"
            "      JOIN pg_class c ON c.oid = ix.indrelid\n"
            "      JOIN pg_class i ON i.oid = ix.indexrelid\n"
            "      JOIN pg_namespace n ON n.oid = c.relnamespace\n"
            "      JOIN pg_stat_all_indexes s ON s.indexrelid = ix.indexrelid\n"
            "      WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')$$\n"
            ");\n"
            "```\n\n"
            "The example above runs weekly (Sundays at 03:00 UTC, `0 3 * * 0`). Adjust to your "
            "own review cadence.\n\n"
            "## Option B: external scheduler\n\n"
            "Where pg_cron is not enabled, run the same population query from an "
            "EventBridge-scheduled Lambda or a scheduled task using the standard read-only "
            "`pg_monitor` role, writing results to your existing metrics store instead of a "
            "database table if preferred.\n\n"
            "## Retention\n\n"
            "Prune old rows on a documented retention window, following the same pattern as "
            "`dba_toolkit.table_size_history` in automation/growth-monitoring.\n"
        ),
        "This is a documentation runbook, not an executable script -- adapt the illustrative DDL/scheduling SQL to your own cadence and storage destination before applying it.",
        related_scripts="../growth-monitoring/README.md, ../../tables-and-indexes/unused-indexes/README.md",
        table_purpose="Scheduling runbook for index-health monitoring (pg_cron or external scheduler).",
    ),
]

# ---------------------------------------------------------------------------
# capacity-monitoring
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="capacity-monitoring",
    title="Scheduled Capacity Threshold Monitoring",
    summary=(
        "The automated, scheduled counterpart to storage-and-capacity/capacity-forecasting "
        "and database-health/capacity-health-check -- both of which are, by design, "
        "point-in-time or manually-triggered reviews. This workflow documents capturing the "
        "same storage, connection, and I/O capacity signals on a recurring schedule with "
        "threshold-based alerting, so a capacity ceiling (storage cost trajectory, "
        "connection headroom, I/O pressure) is flagged automatically as it is approached, "
        "rather than only discovered at the next manually-triggered review."
    ),
    symptoms=[
        "storage-and-capacity/capacity-forecasting or database-health/capacity-health-check has been run manually more than once, and the team wants continuous threshold alerting instead of periodic manual review.",
        "A capacity ceiling (connection exhaustion, a storage cost jump) was reached without any advance warning because the last manual review was weeks earlier.",
    ],
    business_impact=[
        "Connection-capacity exhaustion during a volatility spike is an all-or-nothing failure with no graceful degradation -- scheduled threshold alerting is what catches a climbing utilization trend days or weeks before a spike turns it into an outage.",
        "Storage cost trajectory is a compounding, permanent-on-Aurora cost; catching it via scheduled monitoring rather than at the next manual review shortens the window during which cost accumulates unnoticed.",
    ],
    root_causes=["N/A -- this is a scheduling/automation workflow. See storage-and-capacity/capacity-forecasting and database-health/capacity-health-check for the underlying investigation once a scheduled check crosses a threshold."],
    investigation_strategy=[
        "Capture the same storage-size, connection-headroom, and I/O/checkpoint signals that capacity-forecasting and capacity-health-check already use, on a recurring schedule.",
        "Define concrete alert thresholds for each signal (a connection-utilization percentage, an I/O pressure indicator, a storage growth-rate figure) rather than relying on someone noticing a number looks high during a manual review.",
        "Route threshold breaches to the same alerting/ticketing system used for other operational alerts.",
    ],
    prerequisites=[
        "`pg_monitor` role membership (or `pg_read_all_stats`) for the read-only scripts in this workflow.",
        PG_CRON_PREREQ + " Only required if scheduling via pg_cron; the external-scheduler alternative (recommended for this workflow specifically, since it can alert directly) has no such dependency.",
    ],
    interpretation_guide=[
        "Prefer the external-scheduler pattern for this workflow specifically over a pure pg_cron/table-logging approach: capacity thresholds usually need to page someone directly (a CloudWatch alarm, a PagerDuty integration), and pg_cron alone cannot reach those systems -- it can only write back into the database.",
        "A single scheduled run crossing a threshold once, briefly, during an expected volume event (a known listing, a scheduled batch job) is a different finding from a sustained breach across many consecutive runs -- tune alert sensitivity (e.g. require N consecutive breaches before paging) accordingly.",
    ],
    remediation_immediate=["N/A -- this workflow is scheduling/automation. A specific threshold breach is remediated through storage-and-capacity/capacity-forecasting, connections/max-connections-planning, or the relevant owning workflow."],
    remediation_short_term=["Deploy the scheduled capacity checks and thresholds in this workflow's runbook if they are not already running."],
    remediation_long_term=["Review and adjust alert thresholds periodically as the cluster's baseline instance class, connection pool sizing, and storage footprint change, so thresholds do not become stale relative to a since-changed baseline."],
    production_safety=[
        "Every `.sql` script in this workflow is strictly read-only, identical in safety profile to the storage-and-capacity and database-health scripts it schedules.",
        "The scheduling runbook documents an external scheduler (preferred) or pg_cron invocation -- markdown, never auto-executed by this repository. No configuration or instance-class change is made by anything in this workflow.",
    ],
    escalation_criteria=["A scheduled check reports sustained (not a single transient) breach of a connection-headroom or storage-growth threshold -- escalate to connections/max-connections-planning or storage-and-capacity/capacity-forecasting respectively for the detailed remediation path."],
    related_issues=[
        "../health-checks/README.md",
        "../growth-monitoring/README.md",
        "../../storage-and-capacity/capacity-forecasting/README.md",
        "../../database-health/capacity-health-check/README.md",
        "../../connections/max-connections-planning/README.md",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_storage_and_connection_snapshot",
        "Storage-size and connection-utilization snapshot, intended to be captured on every scheduled run and compared against documented thresholds.",
        sb.database_sizes() + "\n\n" + sb.max_connections_headroom(),
        "pct_utilized against max_connections is the figure to alert on for connection capacity; database size, compared against the previous scheduled run, is the figure to alert on for a storage growth-rate threshold. Neither figure alone is a full capacity picture -- combine with script 02's I/O signal before deciding a threshold breach is genuinely a capacity concern rather than a transient spike.",
        related_scripts="02_io_and_checkpoint_snapshot.sql",
        table_purpose="Database sizes and connection utilization, for scheduled capture.",
    ),
    sql_script(
        "02", "02_io_and_checkpoint_snapshot",
        "Per-backend-type I/O and checkpoint-pressure snapshot, intended to be captured on every scheduled run since I/O-tier capacity is a separate dimension from raw storage bytes.",
        sb.pg_stat_io_summary() + "\n\n" + sb.checkpoint_activity(),
        "A rising pct_forced_checkpoints trend across successive scheduled runs, or a growing read/write byte volume attributable to a specific backend_type, is the early signal that an I/O-tier or checkpoint-tuning review is worth scheduling ahead of any user-visible latency impact -- exactly the same interpretation as storage-and-capacity/capacity-forecasting's equivalent script, just captured automatically instead of on demand.",
        execution_location=WRITER_PREFERRED,
        related_scripts="03_largest_objects_and_growth_trend.sql",
        table_purpose="I/O statistics by backend type and checkpoint activity, for scheduled capture.",
    ),
    sql_script(
        "03", "03_largest_objects_and_growth_trend",
        "Largest-object snapshot plus, where the growth-monitoring collector is deployed, the actual per-table growth rate over the retention window -- the two halves of a capacity trend.",
        sb.largest_tables() + "\n\n" + sb.table_growth_rate_from_snapshot(),
        "The first result is a point-in-time ranking: which objects dominate the volume today. The second is the part that actually supports a forecast, and it only returns rows once automation/growth-monitoring's dba_toolkit.table_size_history collector has been running for at least two collection intervals -- until then it prints an instructional notice, which is the expected state, not an error. Alert on growth rate, not absolute size: a trade-fills, order-events, or audit-ledger table adding a predictable amount per day tells you when the current storage and instance sizing runs out, which is the number a capacity review actually needs. Hand the fastest growers to archival-and-data-lifecycle/archive-large-table or a partitioning plan well before the ceiling.",
        execution_location=WRITER_PREFERRED,
        expected_runtime="Low, but the largest-objects portion touches every relation's size on disk -- run it off-peak on a cluster with very many relations.",
        related_scripts="04_scheduling_runbook.md, ../growth-monitoring/README.md, ../../tables-and-indexes/large-tables/README.md",
        table_purpose="Largest objects now, plus growth over the collector's retention window.",
    ),
    md_script(
        "04", "04_scheduling_runbook",
        "Documents how to schedule the capacity snapshot scripts with threshold-based alerting, via an external scheduler (preferred, since it can alert directly) or pg_cron plus a separate poller.",
        (
            "## Why an external scheduler is usually preferred here\n\n"
            "Unlike growth-monitoring or xid-monitoring, capacity thresholds (connection "
            "utilization, storage growth rate, I/O pressure) typically need to reach an alerting "
            "system directly and quickly. `pg_cron` can only write SQL results back into the "
            "database -- it cannot call CloudWatch, PagerDuty, or Slack itself. An external "
            "scheduler that can call those systems directly is usually the simpler design for "
            "this specific workflow.\n\n"
            "## Option A: external scheduler with direct alerting (recommended)\n\n"
            "An AWS Lambda function on an Amazon EventBridge (CloudWatch Events) scheduled rule:\n\n"
            "1. Connects to the writer endpoint (directly, or via the RDS Data API) using the "
            "standard read-only `pg_monitor` role.\n"
            "2. Runs the snapshot scripts in this workflow.\n"
            "3. Publishes the key figures (`pct_utilized`, database size deltas, "
            "`pct_forced_checkpoints`) as CloudWatch custom metrics.\n"
            "4. Relies on standard CloudWatch alarms on those custom metrics for paging -- this "
            "reuses your existing alerting infrastructure rather than building a new one.\n\n"
            "Recommended starting thresholds (adjust to your own instance class and workload): "
            "connection utilization above 80% sustained for more than one consecutive scheduled "
            "run; a single-review storage size increase materially outside the documented "
            "business growth rate; `pct_forced_checkpoints` above roughly 10% sustained across "
            "several consecutive runs.\n\n"
            "## Option B: pg_cron plus a separate poller\n\n"
            "If pg_cron is already enabled and preferred, schedule the snapshot queries to log "
            "into a `dba_toolkit.capacity_snapshot_history` table (following the same pattern as "
            "`dba_toolkit.table_size_history` in automation/growth-monitoring), and have a "
            "separate lightweight external poller (a small scheduled Lambda, or your existing "
            "metrics-scraping agent) read that table and apply the alerting thresholds. This "
            "still requires an external component to actually page anyone -- pg_cron alone cannot "
            "close that gap.\n\n"
            "## Recommended cadence\n\n"
            "Every 15-60 minutes for connection utilization (it can change quickly during a "
            "volatility spike); daily is sufficient for the storage growth-rate and I/O-pressure "
            "signals, which develop more slowly.\n"
        ),
        "This is a documentation runbook, not an executable script -- adapt the illustrative thresholds and alerting destination to your own instance class, workload, and existing alerting stack before applying it.",
        related_scripts="../health-checks/README.md, ../../storage-and-capacity/capacity-forecasting/README.md, ../../database-health/capacity-health-check/README.md",
        table_purpose="Scheduling runbook for capacity threshold monitoring (external scheduler preferred, or pg_cron).",
    ),
]

