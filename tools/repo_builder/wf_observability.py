"""Workflow definitions: observability/ category (7 issue directories)."""
from __future__ import annotations

from typing import List

from . import sql_blocks as sb
from .helpers import (
    ANY_INSTANCE,
    PG_MONITOR,
    PG_MONITOR_PLUS_PGSS,
    READ_ONLY,
    WRITER_PREFERRED,
    md_script,
    sql_script,
)
from .model import Workflow

CATEGORY_SLUG = "observability"
CATEGORY_TITLE = "Observability"


def _wf(**kwargs) -> Workflow:
    kwargs.setdefault("category_slug", CATEGORY_SLUG)
    kwargs.setdefault("category_title", CATEGORY_TITLE)
    return Workflow(**kwargs)


PGSS_PREREQ = (
    "pg_stat_statements must be present in shared_preload_libraries (Aurora DB "
    "cluster parameter group, requires a reboot to apply) and created in the "
    "current database. This script detects its absence and prints a notice "
    "instead of failing, so it is safe to run either way."
)

REFERENCE_DOC_IMPACT = (
    "None -- this is reference/planning documentation, not an executable script. "
    "Any AWS-side action it describes (enabling a feature, creating an alarm) is "
    "called out explicitly and is a change-managed action outside this repository's "
    "SQL scope."
)


def _pgss_guarded(body: str) -> str:
    """Wrap a pg_stat_statements query in an extension-presence guard.

    Mirrors the equivalent helper in wf_health.py: the guard uses psql's
    ``\\gset`` / ``\\if`` so the script executes unmodified on a database
    where the extension has never been created -- it prints an instructional
    notice rather than raising "relation pg_stat_statements does not exist".
    This module never runs DDL itself: creating an extension is a
    change-managed administrative action, not something an observability
    script may do implicitly.
    """
    return (
        "-- pg_stat_statements presence check. This script never creates the\n"
        "-- extension itself -- it only detects whether it is already available.\n"
        "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements') AS pgss_available\n"
        "\\gset\n"
        "\n"
        "\\if :pgss_available\n"
        f"{body}\n"
        "\\else\n"
        "SELECT 'pg_stat_statements is not installed in this database, so query-level '\n"
        "       'statistics are unavailable. Ask an administrator to add '\n"
        "       'pg_stat_statements to shared_preload_libraries in the Aurora DB '\n"
        "       'cluster parameter group (reboot required) and then run '\n"
        "       'CREATE EXTENSION pg_stat_statements; in a change-managed session. '\n"
        "       'Until then, the wait-event and CloudWatch-based observability in '\n"
        "       'this category still functions without it.'                  AS notice;\n"
        "\\endif"
    )


WORKFLOWS: List[Workflow] = []

# ---------------------------------------------------------------------------
# postgres-metrics
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="postgres-metrics",
    title="Native PostgreSQL Metrics Worth Monitoring Continuously",
    summary=(
        "The core set of native PostgreSQL statistics views and catalogs that a "
        "continuously-running monitoring pipeline (a scheduled collector, an exporter feeding "
        "Prometheus/Grafana, or a periodic health-check job) should read from, and why each one "
        "matters for an exchange-scale Aurora PostgreSQL 17+ deployment. This workflow is the "
        "SQL-level foundation everything else in this category builds on: performance-insights "
        "and cloudwatch add AWS-managed context on top of these same underlying signals, and "
        "dashboard-recommendations proposes how to lay them out for a team to watch continuously."
    ),
    symptoms=[
        "No active symptom -- this is the reference list used when standing up a new monitoring pipeline, onboarding a new cluster, or auditing what an existing dashboard is (or is not) already covering.",
        "An incident review reveals that a metric which would have given early warning was not being collected at all.",
        "A new engineer asks 'what should I actually be watching on this database' and needs a concrete, prioritized answer rather than 'everything'.",
    ],
    business_impact=[
        "Nearly every database incident that reaches an exchange's trading path was observable in these views minutes to days before it became user-visible -- connection headroom, dead tuple accumulation, and XID age all move slowly and predictably if someone (or something) is watching.",
        "Cheap, high-signal counters (cache hit ratio, rollback rate, deadlocks) catch a large fraction of degraded-but-not-yet-failed states for a fraction of the query cost of deep diagnostic queries, which matters when the collector itself must not add meaningful load to a production writer.",
        "A monitoring pipeline that only reads CloudWatch misses everything database-internal: query-level hot spots, dead tuple ratios, and per-table sequential-scan trends are only visible from inside PostgreSQL, not from the instance/hypervisor level CloudWatch observes.",
    ],
    root_causes=[
        "Not a failure workflow -- this is a reference/inventory of what to instrument, not a diagnosis of a specific problem.",
        "The most common gap this workflow closes: a monitoring pipeline built early in a cluster's life that only covers CPU/memory/connections (the CloudWatch-visible basics) and was never extended to cover vacuum health, XID age, or query-level statistics as the platform matured.",
    ],
    investigation_strategy=[
        "Start with connection and session-level state (pg_stat_activity), since it is the highest-frequency, most immediately actionable signal.",
        "Add per-database throughput and cache-efficiency counters (pg_stat_database), the cheapest broad health signal available.",
        "Add table- and index-level activity (pg_stat_user_tables / pg_stat_user_indexes), which is where vacuum debt and lost access paths first become visible.",
        "Add I/O and checkpoint activity (pg_stat_io, pg_stat_checkpointer, pg_stat_bgwriter), the PostgreSQL-side counterpart to CloudWatch's storage-layer metrics.",
        "Add WAL generation, with the Aurora-specific caveat that pg_stat_wal itself cannot be queried on Aurora -- see script 05 and the Aurora notes below.",
        "For each metric, decide the collection frequency (seconds for connections/activity, minutes for throughput/vacuum/WAL) before wiring it into a collector -- these views are cheap individually but querying all of them every few seconds across many databases adds up.",
    ],
    prerequisites=[
        "Role membership in pg_monitor (or pg_read_all_stats) for the monitoring role -- never grant broader privileges just to read statistics views.",
        "A place for the collected values to land (Prometheus via postgres_exporter, CloudWatch custom metrics, or a scheduled table as used by automation/growth-monitoring) -- this workflow defines *what* to collect, not the collector itself.",
        "Awareness that every view here is cumulative since stats_reset (or instantaneous for pg_stat_activity) -- rate/derivative calculation is the collector's job, not something a single query call reveals.",
    ],
    interpretation_guide=[
        "pg_stat_activity is the only view here that is a live snapshot rather than a cumulative counter -- everything else accumulates since stats_reset (typically instance start or the last Aurora failover) and must be diffed between two collection points to get a rate.",
        "A cache hit ratio (pg_stat_database) below roughly 99% on an OLTP exchange workload matters more on Aurora than on self-managed PostgreSQL, because a buffer miss becomes a round trip to the distributed storage layer rather than a local disk read.",
        "Dead tuple ratio and last_autovacuum together (pg_stat_user_tables) distinguish 'autovacuum is losing the race against write volume' from 'autovacuum is not reaching this table at all' -- the two require different fixes.",
        "A rising pct_forced_checkpoints (pg_stat_checkpointer) means checkpoint_timeout/max_wal_size tuning has fallen behind the current write rate -- this is one of the earliest SQL-visible signs of an I/O capacity problem, often before CloudWatch's storage-layer metrics move visibly.",
        "WAL generation cannot be read from pg_stat_wal on Aurora at all -- see script 05's guard and the Aurora notes below before building any alert on this view.",
    ],
    remediation_immediate=[
        "This is an instrumentation workflow, not a remediation workflow -- any specific finding these metrics surface is remediated through its own dedicated category (vacuum-and-autovacuum, connections, tables-and-indexes, and so on).",
    ],
    remediation_short_term=[
        "Wire any metric identified here as currently uncollected into the existing monitoring pipeline, prioritized by which gap would have shortened the most recent incident's time-to-detection.",
        "Set an initial alert threshold from this cluster's own observed baseline (see database-health/daily-health-check for how to establish one), not from a generic published number.",
    ],
    remediation_long_term=[
        "Formalize the collection cadence and retention for each metric family so the trend data survives long enough to support capacity planning, not just alerting on the current value.",
        "Feed the query-level and table-level metrics into the dashboard layout proposed in dashboard-recommendations so they are visible continuously, not only pulled on demand during an investigation.",
    ],
    production_safety=[
        "Every script in this workflow is strictly read-only: catalog and statistics views only, no DDL, no DML, and no session termination.",
        "Individually each script is inexpensive; running the full set on a tight interval (sub-second) across many databases is the only way this workload becomes noticeable -- size the collection frequency to the metric's actual rate of change (seconds for activity, minutes for the rest).",
        "Safe to run against a reader for the database/table/index/I/O metrics; run the connection and activity script against the writer if the writer's own session state is what needs monitoring, since pg_stat_activity is per-instance.",
    ],
    escalation_criteria=[
        "This workflow does not itself define escalation thresholds -- each metric's escalation criteria lives in the workflow that owns that failure mode (see Related Issues).",
        "If auditing an existing pipeline surfaces a complete gap in an entire metric family (for example, no vacuum/XID visibility at all), treat closing that gap as urgent infrastructure work, not a backlog item -- it is the same gap that turns a slow-moving problem into a surprise incident.",
    ],
    related_issues=[
        "../performance-insights/README.md",
        "../cloudwatch/README.md",
        "../dashboard-recommendations/README.md",
        "../../database-health/comprehensive-health-check/README.md",
        "../../vacuum-and-autovacuum/dead-tuples/README.md",
        "../../connections/connection-exhaustion/README.md",
        "../../tables-and-indexes/sequential-scan-investigation/README.md",
    ],
    aurora_notes=[
        "pg_stat_wal is present in the catalog on Aurora PostgreSQL but cannot actually be queried: SELECTing it invokes pg_stat_get_wal(), which Aurora PostgreSQL (verified through 17.7) does not implement, raising 'function pg_stat_get_wal() does not exist'. Script 05 detects Aurora first (via a safe pg_proc-only check, never by calling an Aurora-only function directly) and reports CloudWatch VolumeWriteIOPs/WriteThroughput and the Performance Insights wait-event breakdown as the Aurora-native substitute.",
        "pg_stat_io on PostgreSQL/Aurora 17 has no read_bytes/write_bytes/extend_bytes columns (those were added only in PostgreSQL 18) -- every operation is reported as a count plus a fixed op_bytes, so byte volumes must be derived as reads/writes multiplied by op_bytes, which script 04 already does.",
        "Checkpoint counters live in pg_stat_checkpointer on PostgreSQL 17, not pg_stat_bgwriter (which is now limited to non-checkpoint buffer writes) -- monitoring pipelines built against pre-17 documentation commonly query the wrong view here.",
        "An Aurora failover resets every cumulative counter in this workflow on the promoted instance -- a monitoring pipeline that does not detect and annotate a failover event will show a false 'improvement' in every rate-based metric immediately afterward.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_connection_and_session_metrics",
        "Snapshots current session state grouped by database/state/wait event, and connection utilization against max_connections.",
        sb.activity_overview() + "\n\n" + sb.max_connections_headroom(),
        "This is the highest-frequency signal worth collecting -- a pooled application's connection count and state distribution should look nearly identical from one collection interval to the next. A sudden shift in the state mix (a jump in idle-in-transaction, or in a specific wait_event_type) is actionable within seconds, unlike the slower-moving counters in the rest of this workflow.",
        execution_location=WRITER_PREFERRED,
        related_scripts="02_database_throughput_and_cache_metrics.sql",
        table_purpose="Session state distribution and connection headroom.",
    ),
    sql_script(
        "02", "02_database_throughput_and_cache_metrics",
        "Per-database cumulative throughput, cache hit ratio, rollback ratio, deadlocks, and temp file counters.",
        """
-- The cheapest broad health signal available: one row per database,
-- refreshed continuously by PostgreSQL itself. Every value is cumulative
-- since stats_reset -- a monitoring pipeline should store the raw counters
-- and compute rates/deltas downstream, not just the latest snapshot.
SELECT
    datname                                                      AS database_name,
    numbackends                                                  AS current_backends,
    xact_commit,
    xact_rollback,
    round(100.0 * xact_rollback / NULLIF(xact_commit + xact_rollback, 0), 2) AS rollback_pct,
    blks_hit,
    blks_read,
    round(100.0 * blks_hit / NULLIF(blks_hit + blks_read, 0), 2)  AS cache_hit_pct,
    deadlocks,
    conflicts,
    temp_files,
    temp_bytes,
    checksum_failures,
    stats_reset
FROM pg_stat_database
WHERE datname IS NOT NULL
ORDER BY xact_commit + xact_rollback DESC;
""".strip("\n"),
        "cache_hit_pct is the single most useful number in this view for an OLTP exchange workload -- a sustained drop below roughly 99% means the working set no longer fits in shared_buffers, and on Aurora every miss becomes a network round trip to the distributed storage layer rather than a local page read. Alert on checksum_failures at any non-zero value; it is a storage integrity signal, not a performance one, and must go straight to AWS support.",
        related_scripts="03_table_and_index_activity_metrics.sql",
        table_purpose="Per-database throughput, cache hit ratio, rollbacks, deadlocks, and temp file counters.",
    ),
    sql_script(
        "03", "03_table_and_index_activity_metrics",
        "Dead tuple ratios and vacuum timestamps per table, plus index size and scan-activity inventory.",
        sb.dead_tuples_ranked() + "\n\n" + sb.index_bloat_and_usage(),
        "These two views are where vacuum debt and lost access paths first become visible, well before they show up as latency. Track dead_tuple_pct trend per table (not just its current value) -- a table whose ratio climbs for several consecutive collection intervals is losing the race against its write rate even if the absolute number still looks moderate.",
        expected_runtime="Low to moderate (seconds; scales with the number of tables/indexes in the database).",
        related_scripts="04_io_and_checkpoint_metrics.sql",
        table_purpose="Per-table dead tuple ratios and per-index size/scan activity.",
    ),
    sql_script(
        "04", "04_io_and_checkpoint_metrics",
        "Per-backend-type I/O statistics plus checkpointer and background-writer activity.",
        sb.pg_stat_io_summary() + "\n\n" + sb.checkpoint_activity() + "\n\n" + sb.bgwriter_activity(),
        "pct_forced_checkpoints climbing over successive collections is one of the earliest SQL-visible signs that write volume has outgrown the current checkpoint tuning, often visible here before it shows up in CloudWatch's storage-layer metrics. Remember that on PostgreSQL 17 byte volumes in pg_stat_io are derived (reads/writes times a fixed op_bytes), not read directly from a byte column.",
        related_scripts="05_wal_generation_metrics.sql",
        table_purpose="I/O by backend type, checkpoint activity, and background-writer activity.",
    ),
    sql_script(
        "05", "05_wal_generation_metrics",
        "Cluster-wide WAL generation statistics, with an Aurora-specific availability guard.",
        sb.wal_activity(),
        "On community PostgreSQL this is a direct, valuable rate metric (WAL bytes/sec correlates with both storage growth and replica apply lag). On Aurora PostgreSQL, this view cannot be queried at all -- the script detects this automatically and returns a guidance row pointing at the CloudWatch and Performance Insights equivalents instead of failing. Do not build a monitoring alert directly on this view without first confirming which code path it took in your environment.",
        table_purpose="Cluster-wide WAL generation counters, or an Aurora availability notice.",
    ),
]

# ---------------------------------------------------------------------------
# comprehensive-html-report
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="comprehensive-html-report",
    title="Comprehensive Aurora PostgreSQL HTML Observability Report",
    summary=(
        "A production-validated, self-contained psql report that captures a broad Aurora "
        "PostgreSQL observability snapshot and writes structurally valid HTML for offline "
        "review. It combines configuration, sessions, waits, query statistics, vacuum, "
        "storage, replication, capacity, and extension readiness in one operator-friendly "
        "artifact while dynamically handling optional or unavailable Aurora features."
    ),
    symptoms=[
        "A DBA needs a broad point-in-time health and observability snapshot before narrowing into a symptom-specific workflow.",
        "An incident handoff or review needs a portable HTML artifact that can be opened without database access.",
        "A baseline, post-deployment, or periodic review needs configuration and runtime evidence captured together.",
    ],
    business_impact=[
        "A single report shortens initial triage by collecting related evidence consistently instead of relying on improvised queries.",
        "The portable HTML output supports incident handoffs and audit evidence without exposing database credentials or requiring recipients to connect to production.",
        "Dynamic feature detection prevents optional Aurora extensions or unsupported WAL paths from turning a broad diagnostic run into a partial report.",
    ],
    root_causes=[
        "Not a single-failure workflow: it identifies potential pressure across configuration, sessions, queries, vacuum, storage, replication, and observability coverage.",
        "Findings are point-in-time indicators and must be compared with workload baselines and the focused workflows linked below before remediation.",
    ],
    investigation_strategy=[
        "Confirm the target instance and connect using TLS with a least-privileged monitoring role.",
        "Run the numbered report once with ON_ERROR_STOP enabled and explicit HTML output redirection as documented in scripts/README.md.",
        "Open the generated HTML locally and start with the executive summary and prioritized findings.",
        "Use the detailed sections to validate each finding, then continue in the relevant focused workflow before changing configuration or terminating sessions.",
    ],
    prerequisites=[
        "A supported psql client on Linux, macOS, or Windows; the report depends on psql meta-commands and is not intended for a generic SQL-only client.",
        "CONNECT and TEMPORARY on the target database plus pg_monitor, or equivalent SELECT privileges on the referenced system catalogs and statistics views.",
        "TLS connection settings for the Aurora endpoint. sslmode=verify-full with the current Amazon RDS CA bundle is recommended; sslmode=require encrypts traffic but does not verify server identity.",
        "No extension is mandatory. pg_stat_statements, pg_wait_sampling, apg_plan_mgmt, and version-specific catalog views are detected before use; auto_explain is correctly treated as a preload-only module.",
    ],
    interpretation_guide=[
        "Start with the prioritized findings, but treat thresholds as prompts for investigation rather than automatic remediation decisions.",
        "Session, wait, and instance statistics describe the specific Aurora instance reached by the connection; a reader report does not substitute for a writer report when investigating writer load.",
        "Unavailable sections are explicitly reported when an extension or Aurora PostgreSQL path is unsupported; absence of that section's metrics is not evidence that the underlying workload is healthy.",
        "Keep the generated HTML only in an approved local evidence location because it can contain database names, role names, query text, schema names, and operational metadata. Generated reports are intentionally excluded from this repository.",
    ],
    remediation_immediate=[
        "Do not apply recommendations directly from the HTML report during an incident. Confirm the signal in the linked focused workflow and use its safety and escalation guidance.",
    ],
    remediation_short_term=[
        "Compare findings with the cluster's normal baseline and open targeted follow-up work for confirmed configuration, vacuum, query, replication, or capacity issues.",
        "Re-run after approved changes to capture before-and-after evidence using the same target instance and monitoring role.",
    ],
    remediation_long_term=[
        "Schedule periodic runs only at a cadence appropriate for database size and retain reports under the organization's security and incident-evidence policy.",
        "Use recurring findings to improve continuous dashboards and alerts rather than relying on a comprehensive snapshot as the primary monitoring system.",
    ],
    production_safety=[
        "The report is LOW RISK WRITE, not READ ONLY: it creates and populates only one temporary table scoped to the psql session; it does not write application tables or persist database objects.",
        "The report reads many system catalogs and statistics views. Runtime is typically seconds to several minutes but scales with object count, statement statistics, and database size; avoid repeatedly running it during peak load.",
        "The report prints recommendations that may mention disruptive actions. Those strings are output only and are never executed by this script.",
        "Use -v ON_ERROR_STOP=1 so a failed section stops the run instead of producing a success-looking partial artifact.",
    ],
    escalation_criteria=[
        "Any critical finding that affects availability, transaction ID safety, replication, or connection headroom is confirmed by the corresponding focused workflow.",
        "The report cannot complete with the documented role because required catalog visibility is restricted; involve the database platform owner rather than broadening privileges ad hoc.",
        "Runtime or load is materially higher than the documented range; stop repeated runs and use narrower scripts while investigating the cause.",
    ],
    related_issues=[
        "../postgres-metrics/README.md",
        "../slow-query-observability/README.md",
        "../wait-event-analysis/README.md",
        "../../database-health/comprehensive-health-check/README.md",
        "../../vacuum-and-autovacuum/autovacuum-not-keeping-up/README.md",
        "../../replication-and-ha/replication-health/README.md",
        "../../storage-and-capacity/capacity-forecasting/README.md",
    ],
    aurora_notes=[
        "This report is derived from [`platforms/aurora-postgresql/aws-rds/postgres_observability_report.sql`](https://github.com/Nitish-Anand-Srivastava/database-reliability-engineering/blob/main/platforms/aurora-postgresql/aws-rds/postgres_observability_report.sql), production-validated against Aurora PostgreSQL 17.7 after Nitish-Anand-Srivastava/database-reliability-engineering#16. This repository adds its standard script header plus safe `psql -o` invocation guidance and validator-safe rendering adjustments.",
        "Aurora extensions are not assumed available. Extension and module checks distinguish installed extensions, unavailable extensions, and auto_explain's shared_preload_libraries-only activation model.",
        "Unsupported Aurora WAL statistics paths are guarded so the report records availability guidance rather than aborting.",
        "Settings with PostgreSQL unit suffixes are interpreted through catalog metadata rather than assuming every setting is a bare integer.",
    ],
    execution_guidance=r"""
Run from the repository root. Both examples write
`postgres_observability_report.html` in the current directory and stop at the
first SQL or psql error. Credentials should come from a secure prompt,
`.pgpass`/`pgpass.conf`, IAM authentication, or the organization's secret
manager; never put a password in the command, report, or repository.

**Linux/macOS (bash):**

```bash
PGHOST=db.example.internal \
PGPORT=5432 \
PGDATABASE=appdb \
PGUSER=monitoring \
PGSSLMODE=verify-full \
PGSSLROOTCERT=/etc/ssl/certs/rds-ca-rsa2048-g1.pem \
psql -X -v ON_ERROR_STOP=1 \
  -f observability/comprehensive-html-report/scripts/01_postgres_observability_report.sql \
  -o postgres_observability_report.html
```

**Windows (PowerShell):**

```powershell
$env:PGHOST = "db.example.internal"
$env:PGPORT = "5432"
$env:PGDATABASE = "appdb"
$env:PGUSER = "monitoring"
$env:PGSSLMODE = "verify-full"
$env:PGSSLROOTCERT = "C:\certs\rds-ca-rsa2048-g1.pem"
psql.exe -X -v ON_ERROR_STOP=1 `
  -f "observability\comprehensive-html-report\scripts\01_postgres_observability_report.sql" `
  -o "postgres_observability_report.html"
```

If the RDS CA bundle is not yet available, `sslmode=require` still encrypts
the connection but does not verify the endpoint identity; install the CA
bundle and use `verify-full` for production. The output may contain sensitive
operational metadata and query text, so review and store it accordingly.
""",
    expected_output_guidance=(
        "The command writes a self-contained `postgres_observability_report.html` "
        "file. Open it locally in a modern browser and begin with the executive "
        "summary and prioritized findings. The file can contain database names, "
        "roles, schema metadata, and query text; handle it as production operational "
        "evidence rather than a public artifact."
    ),
    severe_incident_guidance=(
        "_This report is LOW RISK WRITE because it uses a session-scoped temporary "
        "table, and its broad catalog/statistics scan can add avoidable load. During "
        "a severe incident, prefer the narrow symptom-specific scripts first; run "
        "the comprehensive report once only when the instance has sufficient "
        "headroom._"
    ),
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_postgres_observability_report",
        "Generates a self-contained HTML snapshot spanning Aurora PostgreSQL configuration, workload, waits, queries, maintenance, storage, replication, capacity, and observability readiness.",
        "",
        "Open postgres_observability_report.html in a browser, begin with the executive summary and prioritized findings, and corroborate each recommendation in the corresponding detailed section and focused repository workflow before acting.",
        safety="LOW RISK WRITE (session-scoped temporary table only)",
        expected_impact="Low to moderate -- creates one session-local temporary table and scans system catalogs/statistics views; typically seconds to several minutes, scaling with database object count and statistics volume.",
        required_privileges="CONNECT and TEMPORARY on the target database plus pg_monitor (or equivalent SELECT access to the referenced system views). No superuser is required.",
        prerequisites="psql with TLS configured. Optional extensions are dynamically detected; none is required for the report to complete.",
        execution_location=WRITER_PREFERRED,
        expected_runtime="Typically seconds to several minutes; run once and avoid repeated execution during peak load.",
        table_purpose="Complete Aurora PostgreSQL observability snapshot rendered as a local HTML file.",
        generator_managed=False,
    ),
]

# ---------------------------------------------------------------------------
# performance-insights
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="performance-insights",
    title="Using AWS Performance Insights Alongside SQL Diagnostics",
    summary=(
        "AWS Performance Insights (PI) samples pg_stat_activity roughly once per second and "
        "aggregates it into Average Active Sessions (AAS) broken down by wait event, SQL "
        "statement, user, and host -- the same underlying source data this repository's "
        "SQL-level scripts read on demand, but continuously recorded, retained, and rendered as "
        "a stacked timeline. This workflow explains how to read PI's DB load view correctly, "
        "when to reach for it before a SQL session, and how to cross-reference its findings back "
        "against the live catalog queries in this repository to confirm and drill into what it "
        "shows."
    ),
    symptoms=[
        "Overall database load or latency is elevated and the specific cause is not yet known -- the classic entry point for PI's DB load view before drilling into any specific SQL script.",
        "An incident needs a historical view of load at a specific past timestamp (a spike ten minutes ago) that a live pg_stat_activity query can no longer see.",
        "high-database-load or a similar performance investigation needs a wait-event-centric breakdown of exactly where active sessions were spending their time.",
    ],
    business_impact=[
        "PI's continuous one-second sampling captures a wait-event-level breakdown of a transient spike that a live SQL query, run only after someone notices a problem, has already missed by the time anyone looks.",
        "The DB load view's wait-event coloring turns 'the database feels slow' into a specific, actionable category (CPU vs. Lock vs. IO vs. IPC) in seconds, without needing to construct or remember the equivalent catalog query first.",
        "Because PI requires no additional load on the database itself (it samples via the RDS/Aurora control plane, not a client connection), it remains available and readable even when the database is under enough load or connection pressure that opening a new psql session is itself difficult.",
    ],
    root_causes=[
        "Not a failure workflow -- this explains how to use an observability tool, not a specific failure mode.",
        "The most common misuse this workflow corrects: treating PI's DB load number as a single global 'health score' rather than reading its wait-event/SQL/user breakdown, which is where the actual diagnostic value is.",
    ],
    investigation_strategy=[
        "Open the PI console (or the GetResourceMetrics API) for the instance and time window in question and read the DB load view's stacked wait-event breakdown before anything else -- it costs nothing to check and often narrows the search immediately.",
        "If DB load is dominated by CPU, corroborate with a live wait-event snapshot (script 01) and CPU-focused SQL diagnostics (performance/high-cpu) rather than assuming PI's classification alone is the full picture.",
        "If DB load is dominated by a non-CPU wait event (Lock, IO, IPC), switch PI's view to break down by that wait event and by SQL statement/queryid to identify the specific statement or session responsible.",
        "Cross-reference the queryid PI surfaces against pg_stat_statements directly (script 02, or slow-query-observability) to get the full query text and execution statistics PI's UI may truncate.",
        "For a currently ongoing spike, corroborate PI's historical view with the live per-session detail in wait-event-analysis, since PI aggregates while a live query shows individual sessions and their exact query text.",
    ],
    prerequisites=[
        "Performance Insights enabled on the target DB instance (it is enabled by default for new Aurora PostgreSQL instances since a certain console/CLI default, but existing instances may have it off -- see script 03 for how to check and enable it).",
        "IAM permission to view Performance Insights for the instance (pi:GetResourceMetrics / pi:DescribeDimensionKeys or console equivalent) -- this is an AWS IAM permission, separate from any PostgreSQL role.",
        "Role membership in pg_monitor (or pg_read_all_stats) for the SQL-side cross-reference scripts.",
        "pg_stat_statements installed for the queryid cross-reference step (PI's own sampling does not require it, but confirming what a queryid actually is does).",
    ],
    interpretation_guide=[
        "DB load is measured in Average Active Sessions: a DB load of 1.0 for a given period means, on average, one session was found active (not idle) each time PI sampled. Compare DB load against the instance's vCPU count -- sustained DB load meaningfully above vCPU count means sessions are queuing for something, not just using available CPU in parallel.",
        "The wait-event coloring in PI's stacked chart is the same wait_event_type taxonomy pg_stat_activity itself exposes (CPU, Lock, LWLock, IO, IPC, Timeout, Client, Extension, BufferPin) -- wait-event-analysis in this same category documents what each one means in detail.",
        "PI's 'Top SQL' and 'Top Waits' tabs are ranked by their contribution to DB load (AAS), which is a different ranking from pg_stat_statements' total_exec_time -- a statement can dominate DB load by being active-and-waiting very often without having the highest cumulative execution time, and vice versa.",
        "PI retains one week of data at the default (free) retention tier and up to two years at the long-term (paid) tier -- for a suspected recurring pattern (weekly settlement, month-end reconciliation), confirm the retention tier before assuming historical data is still available.",
        "PI samples via the RDS/Aurora control plane at roughly one-second granularity; it can slightly under- or over-represent extremely short-lived sessions compared to a continuous trace, so treat single-second spikes as directional rather than exact.",
    ],
    remediation_immediate=[
        "This workflow is diagnostic, not remedial -- once PI or the SQL cross-reference identifies the responsible wait event and statement, route to the dedicated workflow that owns that failure mode (performance/high-cpu, concurrency-and-locking/lock-contention, and so on).",
    ],
    remediation_short_term=[
        "If PI is not yet enabled on a production instance, enable it (script 03) so the next incident has this historical view available -- there is no reason to run without it given its low overhead and low cost at the default 7-day retention.",
        "Bookmark or export the specific PI console URL/time-range for an incident's review, since the console view is easiest to share with a team that does not have SQL access.",
    ],
    remediation_long_term=[
        "Enable the long-term (paid) PI retention tier on clusters where recurring monthly/quarterly patterns (settlement, reconciliation, compliance reporting) need to be compared across cycles longer than a week.",
        "Fold PI's DB load metric into the dashboard proposed in dashboard-recommendations, so wait-event trends are visible continuously rather than only pulled up during an active incident.",
    ],
    production_safety=[
        "Performance Insights itself imposes negligible overhead on the database -- it samples via the RDS/Aurora control plane, not through a client connection, so viewing it never adds query load.",
        "Every SQL script in this workflow is strictly read-only and safe to run at any time, including during an active incident.",
        "Enabling Performance Insights on an existing instance (script 03) may require a brief modification window on some older instance classes -- read the runbook's caveats before scheduling it, and prefer doing so outside peak trading hours the first time.",
    ],
    escalation_criteria=[
        "DB load sustained meaningfully above the instance's vCPU count for an extended period, with no corresponding drop in application throughput explaining it as expected -- escalate to performance/high-database-load.",
        "PI's Top Waits view is dominated by Lock wait events for more than a few minutes -- escalate to concurrency-and-locking/lock-contention immediately rather than waiting for a live SQL session to confirm it.",
        "PI shows a load spike that has already ended by the time it is noticed and no live session data remains -- this is exactly the scenario PI exists for; do not conclude 'nothing to investigate' just because a live pg_stat_activity query now looks clean.",
    ],
    related_issues=[
        "../postgres-metrics/README.md",
        "../wait-event-analysis/README.md",
        "../cloudwatch/README.md",
        "../slow-query-observability/README.md",
        "../../performance/high-database-load/README.md",
        "../../concurrency-and-locking/lock-contention/README.md",
    ],
    aurora_notes=[
        "Performance Insights on Aurora PostgreSQL reports at the DB instance level, not the cluster level -- a reader under load and the writer under load show up as separate PI resources; check the correct instance identifier, especially right after a failover changed which instance is the writer.",
        "PI's wait-event taxonomy matches PostgreSQL's own pg_stat_activity.wait_event_type/wait_event columns directly on Aurora, unlike some managed-database services that remap wait events to a proprietary taxonomy -- cross-referencing PI's chart against a live wait_events_summary() query (script 01) works because they are the same underlying classification.",
        "A failover changes which instance is the writer; PI's per-instance view does not automatically follow the writer role, so after a failover, re-identify which PI resource corresponds to the new writer before comparing pre/post-failover load.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_current_wait_event_snapshot",
        "Aggregates current backends by wait event, the same taxonomy Performance Insights uses to color its DB load chart.",
        sb.wait_events_summary(),
        "Use this to sanity-check what PI's console is showing right now, or as the fallback when PI is not yet enabled on this instance. A concentration of backends in a single wait_event_type mirrors exactly what a spike in PI's stacked chart at this moment would show.",
        related_scripts="02_active_session_load_by_query.sql, ../wait-event-analysis/README.md",
        table_purpose="Current backend counts by wait event type/name.",
    ),
    sql_script(
        "02", "02_active_session_load_by_query",
        "Groups currently active sessions by query_id and wait event, approximating PI's Top SQL / DB load by SQL breakdown from live catalog data.",
        """
-- Approximates Performance Insights' "DB load by SQL" breakdown using only
-- native catalog data -- useful when PI is not yet enabled, or when
-- cross-referencing a queryid PI surfaced against the exact live query text.
-- PostgreSQL 14+ (unchanged through 17) exposes query_id directly on
-- pg_stat_activity once compute_query_id is active, which pg_stat_statements
-- already requires internally -- so on any instance running
-- pg_stat_statements this is populated with no extra configuration.
SELECT
    a.query_id,
    a.wait_event_type,
    a.wait_event,
    count(*)                                                    AS active_session_count,
    array_agg(DISTINCT a.datname)                               AS databases,
    left(max(a.query), 200)                                     AS sample_query_text
FROM pg_stat_activity a
WHERE a.pid <> pg_backend_pid()
  AND a.state = 'active'
GROUP BY a.query_id, a.wait_event_type, a.wait_event
ORDER BY active_session_count DESC;
""".strip("\n"),
        "active_session_count per query_id is this instant's contribution to DB load from that statement -- the same concept as PI's AAS-by-SQL ranking, just computed live instead of from PI's continuous sampling. Take query_id to pg_stat_statements (slow-query-observability) for the statement's full cumulative execution statistics rather than relying on the truncated sample_query_text here.",
        related_scripts="03_enabling_and_interpreting_performance_insights.md",
        table_purpose="Active sessions grouped by query_id and wait event, approximating DB load by SQL.",
    ),
    md_script(
        "03", "03_enabling_and_interpreting_performance_insights",
        "Runbook for confirming/enabling Performance Insights on a DB instance and reading its DB load view correctly during an investigation.",
        """
## Checking whether Performance Insights is enabled

Performance Insights is a property of the DB *instance* (not the cluster),
configured through the AWS Console, CLI, or infrastructure-as-code -- it is
not something a SQL script can query from inside PostgreSQL. Check via the
CLI:

```
aws rds describe-db-instances \\
  --db-instance-identifier <instance-identifier> \\
  --query 'DBInstances[0].PerformanceInsightsEnabled'
```

## Enabling it on an existing instance

Enabling Performance Insights on an instance that does not already have it
is a change-managed infrastructure action, not a database statement, and is
therefore described here rather than shipped as SQL:

```
aws rds modify-db-instance \\
  --db-instance-identifier <instance-identifier> \\
  --enable-performance-insights \\
  --performance-insights-retention-period 7 \\
  --apply-immediately
```

Review before running: on some older instance classes this can require a
brief instance modification window; test on a non-writer instance first if
this cluster has never had it enabled, and avoid `--apply-immediately`
during peak trading hours on the writer if the change can instead wait for
the next scheduled maintenance window.

## Reading the DB load view

1. Open the instance's Performance Insights dashboard and select the
   incident's time range.
2. Read the DB load line against the instance's vCPU count (shown as a
   reference line) before anything else -- load below vCPU count usually
   means available parallelism, not contention.
3. Switch the breakdown dimension to "Wait event" first to classify the
   load (CPU / Lock / IO / IPC / other), then to "SQL" to identify the
   responsible statement(s) within the dominant wait event.
4. Cross-reference the queryid shown against script 02 (if the load is
   current) or pg_stat_statements directly (if pg_stat_statements has not
   been reset since the incident) for the full statement text and stats.

## When PI alone is not enough

Performance Insights aggregates; it does not show individual session
identity, client address, or the exact current query text of a specific
backend. For that level of detail on a currently ongoing issue, use the
live per-session scripts in wait-event-analysis and
concurrency-and-locking/blocked-queries alongside PI's historical view.
""".strip("\n"),
        "Follow the numbered steps in order during a live investigation. The enable/modify step is the only part of this runbook that changes anything -- everything else is read-only console/API usage.",
        safety="INFORMATIONAL -- NO SQL EXECUTED, AWS CONSOLE/API GUIDANCE ONLY (the enable step is a change-managed AWS instance modification -- see runbook)",
        expected_impact=REFERENCE_DOC_IMPACT,
        required_privileges="IAM permission to describe/modify the DB instance and to view Performance Insights (pi:GetResourceMetrics, pi:DescribeDimensionKeys, rds:ModifyDBInstance) for the enable step; no PostgreSQL role required for the console/API portions.",
        prerequisites="None to read this runbook. Enabling Performance Insights on an existing instance should be scheduled like any other instance-modifying change.",
        execution_location=ANY_INSTANCE,
        expected_runtime="A few minutes to check/enable; the console investigation itself is as long as the incident review requires.",
        related_scripts="../wait-event-analysis/README.md, ../../performance/high-database-load/README.md",
        table_purpose="Runbook: confirm/enable Performance Insights and read its DB load view during an investigation.",
    ),
]

# ---------------------------------------------------------------------------
# cloudwatch
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="cloudwatch",
    title="CloudWatch Metrics for Aurora PostgreSQL",
    summary=(
        "The Aurora-published CloudWatch metrics an on-call DBA and platform team should already "
        "have alarms on, and -- for each one -- the SQL-level query in this repository that "
        "explains *why* the metric moved. CloudWatch metrics come from the instance/hypervisor "
        "and Aurora storage layer, not from inside PostgreSQL, so they answer 'something changed' "
        "reliably but rarely 'what changed inside the database'; this workflow is the bridge "
        "between the two."
    ),
    symptoms=[
        "A CloudWatch alarm has fired (CPUUtilization, DatabaseConnections, FreeableMemory, DiskQueueDepth, or similar) and the database-level cause is not yet known.",
        "A capacity or cost review is looking at VolumeBytesUsed or connection trend lines and wants the SQL-level explanation behind the trend.",
        "A new cluster is being onboarded and the team needs to know which CloudWatch metrics to alarm on in the first place.",
    ],
    business_impact=[
        "CloudWatch alarms are almost always the first signal an on-call engineer sees, often before any application-level alert -- knowing immediately which SQL script corresponds to a given metric turns 'an alarm fired' into 'here is what is happening inside the database' in the first minute of an incident, not the tenth.",
        "AuroraReplicaLag and BufferCacheHitRatio moving in the wrong direction are both directly user-visible on an exchange (stale reads, degraded latency) well before CPUUtilization or DatabaseConnections would suggest a problem, so alarming on the right metrics matters as much as alarming on the obvious ones.",
        "VolumeBytesUsed is a direct, ongoing infrastructure cost on Aurora (storage billed on the shared cluster volume, never reclaimed automatically) -- connecting its trend line back to the specific tables or WAL retention driving it turns a cost conversation into an actionable engineering ticket.",
    ],
    root_causes=[
        "Not a failure workflow -- this maps monitoring signals to their SQL-level explanation rather than diagnosing a specific failure.",
        "The most common gap this workflow closes: a team alarming only on CPUUtilization and DatabaseConnections while ignoring AuroraReplicaLag, BufferCacheHitRatio, or DiskQueueDepth, all of which degrade user experience on an exchange well before CPU or connection count would.",
    ],
    investigation_strategy=[
        "Identify which specific CloudWatch metric triggered the investigation and its exact time window.",
        "Run the SQL-side capacity and load snapshot for the current values of the metrics that have a direct database-internal counterpart.",
        "For AuroraReplicaLag specifically, run the Aurora-native replica status query rather than assuming pg_stat_replication will show anything (it does not, for Aurora readers).",
        "Use the metric-to-SQL mapping reference to identify which workflow in this repository owns deeper investigation of the specific metric that moved.",
        "For a metric with no direct SQL-level counterpart (CPUUtilization, FreeableMemory), correlate its timing against the DB-side signals available (query volume, cache hit ratio, checkpoint activity) rather than expecting a single query to explain it.",
    ],
    prerequisites=[
        "CloudWatch console/API access scoped to the RDS/Aurora namespace for the account and region.",
        "Role membership in pg_monitor (or pg_read_all_stats) for the SQL-side scripts.",
        "Alarms already configured, or this workflow's mapping table used as the starting checklist for configuring them.",
    ],
    interpretation_guide=[
        "CloudWatch metrics are authoritative for anything infrastructure- or billing-level (actual CPUUtilization, actual billed VolumeBytesUsed); the SQL-side queries in this workflow are a proxy that explains the *database-visible* contributor, and the two will not always match exactly (for example, VolumeBytesUsed includes storage Aurora has allocated but not yet reported back to pg_database_size()).",
        "DatabaseConnections (CloudWatch) and current_connections (SQL) should track closely; a persistent gap between them usually means connections from a source CloudWatch is not correctly attributing (rare) or a metric collection delay, not a real discrepancy.",
        "BufferCacheHitRatio (CloudWatch) and cache_hit_pct_all_databases (SQL, script 01) measure the same underlying phenomenon at slightly different granularity (instance-wide vs. per-database) -- expect them to move together, not to match to the decimal.",
        "AuroraReplicaLag (CloudWatch, per-reader) and the lag reported by aurora_replica_status() (SQL, script 02) are the same underlying Aurora storage-layer replication mechanism -- use the SQL version when you need to query from any instance in the cluster without switching AWS console context.",
        "DiskQueueDepth and VolumeReadIOPs/VolumeWriteIOPs have no single equivalent SQL counter; pg_stat_checkpointer's pct_forced_checkpoints and pg_stat_io's read/write counts are the closest SQL-visible proxies and are directional, not a byte-for-byte match.",
    ],
    remediation_immediate=[
        "This workflow is diagnostic/mapping, not remedial -- once the SQL-side counterpart identifies the responsible internal behavior, route to the dedicated workflow that owns it (see the mapping reference and Related Issues).",
    ],
    remediation_short_term=[
        "Add any alarm identified as missing from the mapping reference (script 03) to this cluster's CloudWatch alarm configuration, using this cluster's own observed baseline for the threshold rather than a generic published number.",
        "For a metric with an established SQL-level companion query, add that query's output to the incident ticket alongside the CloudWatch graph so the review has both the infrastructure and database-internal view together.",
    ],
    remediation_long_term=[
        "Build the recommended alarm set from the mapping reference into infrastructure-as-code so every new cluster starts with the full set rather than only the metrics someone remembered to configure.",
        "Feed both the CloudWatch metrics and their SQL-side companions into the dashboard layout proposed in dashboard-recommendations so the two are viewed side by side routinely, not only reconstructed during an incident.",
    ],
    production_safety=[
        "Reading CloudWatch metrics imposes no load on the database at all -- it is a separate AWS service reading instance/hypervisor and storage-layer telemetry.",
        "Every SQL script in this workflow is strictly read-only and safe to run at any time, including during an active incident.",
        "Creating or modifying a CloudWatch alarm (described in script 03's reference material) is an AWS-side configuration action with no database impact, but should still go through normal change review since it affects on-call paging behavior.",
    ],
    escalation_criteria=[
        "AuroraReplicaLag sustained above the application's read-your-own-write tolerance -- escalate to replication-and-ha/reader-lag-investigation.",
        "BufferCacheHitRatio trending down over successive days with no corresponding traffic explanation -- escalate to performance/high-iops or database-health/capacity-health-check.",
        "DatabaseConnections approaching max_connections with the SQL-side connections/max-connections-planning headroom check confirming the same -- escalate immediately, this is a hard ceiling with no graceful degradation.",
        "VolumeBytesUsed growing faster than the documented business growth rate with no SQL-side table growth explaining the difference -- escalate to storage-and-capacity/unexpected-storage-growth to check for retained WAL or an orphaned replication slot.",
    ],
    related_issues=[
        "../postgres-metrics/README.md",
        "../performance-insights/README.md",
        "../dashboard-recommendations/README.md",
        "../../replication-and-ha/replication-lag/README.md",
        "../../connections/max-connections-planning/README.md",
        "../../storage-and-capacity/database-growth/README.md",
    ],
    aurora_notes=[
        "AuroraReplicaLag has no meaning on a standalone/single-instance cluster and reports per-reader on a multi-instance Aurora cluster -- it is not the same metric as, and should not be confused with, standard PostgreSQL streaming replication lag on a self-managed replica.",
        "VolumeBytesUsed reflects Aurora's shared cluster storage volume, which grows in 10GiB increments and is never reduced by deleting rows or dropping objects -- do not expect it to track pg_database_size() precisely, and do not expect it to shrink after an archival/purge operation the way logical size will.",
        "CPUUtilization and FreeableMemory on Aurora are reported per-instance (writer and each reader separately) -- when correlating against a SQL-side query, make sure the SQL session and the CloudWatch graph are pointed at the same specific instance, not merely 'the cluster'.",
        "Aurora storage I/O (VolumeReadIOPs/VolumeWriteIOPs) is billed and capacity-planned separately from compute; a CPUUtilization metric that looks comfortable does not mean I/O capacity is comfortable too -- check both independently.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_sql_side_capacity_and_load_snapshot",
        "One-row snapshot of the SQL-visible counterparts to the most commonly alarmed-on Aurora CloudWatch metrics.",
        """
-- One-row snapshot of the SQL-visible counterparts to the most commonly
-- alarmed-on Aurora CloudWatch metrics, for direct comparison against the
-- CloudWatch console/API when investigating an alarm. This is a proxy, not
-- a replacement: CloudWatch's data comes from the hypervisor/engine level
-- and storage layer and is authoritative for anything billing- or
-- infrastructure-related (actual VolumeBytesUsed, actual CPUUtilization);
-- this query shows what PostgreSQL itself can see, which is what usually
-- explains *why* a CloudWatch metric moved.
SELECT
    (SELECT count(*) FROM pg_stat_activity)                                   AS current_connections,
    (SELECT setting::int FROM pg_settings WHERE name = 'max_connections')     AS max_connections,
    round(
        100.0 * (SELECT count(*) FROM pg_stat_activity) /
        NULLIF((SELECT setting::numeric FROM pg_settings WHERE name = 'max_connections'), 0),
        2
    )                                                                          AS pct_connections_used,
    round(
        100.0 * sum(blks_hit) / NULLIF(sum(blks_hit) + sum(blks_read), 0), 2
    )                                                                          AS cache_hit_pct_all_databases,
    (SELECT round(100.0 * num_requested / NULLIF(num_timed + num_requested, 0), 2)
     FROM pg_stat_checkpointer)                                               AS pct_forced_checkpoints,
    pg_size_pretty(sum(pg_database_size(datname)))                            AS total_logical_database_size,
    sum(temp_bytes)                                                           AS total_temp_bytes_since_reset
FROM pg_stat_database
WHERE datname IS NOT NULL;
""".strip("\n"),
        "Compare pct_connections_used against CloudWatch's DatabaseConnections/max_connections, cache_hit_pct_all_databases against BufferCacheHitRatio, and pct_forced_checkpoints as a proxy for rising DiskQueueDepth/IOPS pressure. total_logical_database_size is not the same number as VolumeBytesUsed (see Aurora notes) but its trend should move in the same direction.",
        execution_location=WRITER_PREFERRED,
        related_scripts="02_replication_lag_sql_companion.sql",
        table_purpose="One-row SQL-side snapshot mapped to key CloudWatch metrics.",
    ),
    sql_script(
        "02", "02_replication_lag_sql_companion",
        "Aurora-native cluster-wide replica status and lag, the SQL-side companion to the AuroraReplicaLag CloudWatch metric.",
        sb.aurora_replica_status(),
        "This is the correct SQL-side companion to AuroraReplicaLag -- pg_stat_replication will not show Aurora readers at all (see the Aurora notes). Run this from any instance in the cluster; it does not need to be the writer. A reader whose lag here is elevated should show the same elevation in its CloudWatch AuroraReplicaLag graph -- if the two disagree substantially, suspect a metric collection delay before suspecting the query.",
        related_scripts="03_cloudwatch_metric_to_sql_mapping.md, ../../replication-and-ha/replication-lag/README.md",
        table_purpose="Aurora cluster replica status and lag, per reader.",
    ),
    md_script(
        "03", "03_cloudwatch_metric_to_sql_mapping",
        "Reference table mapping key Aurora CloudWatch metrics to their SQL-level companion query and recommended alarm guidance.",
        """
## Metric-to-SQL mapping

| CloudWatch metric | SQL-level companion | Notes |
| --- | --- | --- |
| `CPUUtilization` | No direct SQL counterpart; correlate with query volume/type via slow-query-observability | Sustained high CPU with low active-session count suggests a few CPU-heavy statements; use performance-insights to identify them. |
| `DatabaseConnections` | `pct_connections_used` (script 01) | Should track closely; alarm at ~80% of `max_connections` as an early warning, not only at exhaustion. |
| `FreeableMemory` | No direct SQL counterpart; correlate with `work_mem`/`shared_buffers` settings and temp file growth (script 01, `total_temp_bytes_since_reset`) | A shrinking trend alongside rising temp file volume suggests memory pressure from oversized sort/hash operations. |
| `VolumeBytesUsed` | `total_logical_database_size` (script 01), plus `database-health/capacity-health-check` for the full breakdown | Aurora storage never shrinks automatically; a rising trend with no matching logical size growth suggests retained WAL (replication slots) rather than table growth. |
| `VolumeReadIOPs` / `VolumeWriteIOPs` | `pg_stat_io` counts, `pct_forced_checkpoints` (script 01) | No exact SQL equivalent; both are directional proxies for I/O pressure at the storage layer. |
| `AuroraReplicaLag` | `aurora_replica_status()` (script 02) | Per-reader metric; always use the Aurora-native function, never `pg_stat_replication`, for Aurora readers. |
| `BufferCacheHitRatio` | `cache_hit_pct_all_databases` (script 01) | Instance-wide vs. per-database granularity; expect close tracking, not exact equality. |
| `DiskQueueDepth` | `pct_forced_checkpoints`, `pg_stat_io` read/write counts (script 01, postgres-metrics script 04) | No exact SQL equivalent; treat as directional. |

## Recommended baseline alarm set

At minimum, alarm on: `DatabaseConnections` (approaching `max_connections`),
`FreeableMemory` (approaching zero), `VolumeBytesUsed` (unexpected growth
rate), `AuroraReplicaLag` (above the application's read-your-own-write
tolerance), and `CPUUtilization` (sustained high). Configuring or updating
these alarms is an AWS-side action (console, CLI, or infrastructure-as-code)
and should go through the same change review as any other alerting change,
since it affects on-call paging behavior.

## How to use this table during an incident

1. Identify which CloudWatch metric triggered the alert and its exact time
   window.
2. Find its row in the mapping table above and run the referenced SQL
   script for the current, SQL-visible picture.
3. If the metric has no direct SQL companion, use the "Notes" column's
   correlation guidance rather than searching for a query that does not
   exist.
4. Route the finding to the dedicated workflow in this repository that
   owns the underlying database behavior, using this table as the index.
""".strip("\n"),
        "Use the table to go from 'this CloudWatch alarm fired' to 'this is the SQL script that explains it' in one lookup, without needing to remember the mapping from memory during an incident.",
        safety="INFORMATIONAL -- NO SQL EXECUTED, AWS CONSOLE/API GUIDANCE ONLY (reference mapping; any CloudWatch alarm change is a change-managed AWS action)",
        expected_impact=REFERENCE_DOC_IMPACT,
        required_privileges="IAM permission to view CloudWatch metrics/alarms for the console portions; the SQL scripts this table points at require pg_monitor as usual.",
        prerequisites="None to read this reference. The scripts it links to have their own prerequisites.",
        execution_location=ANY_INSTANCE,
        expected_runtime="A few minutes to read; the referenced SQL scripts are each low runtime individually.",
        related_scripts="01_sql_side_capacity_and_load_snapshot.sql, 02_replication_lag_sql_companion.sql",
        table_purpose="Reference: CloudWatch metric to SQL-level companion query mapping.",
    ),
]

# ---------------------------------------------------------------------------
# slow-query-observability
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="slow-query-observability",
    title="Building Durable Slow-Query Observability",
    summary=(
        "How to build standing, always-on visibility into slow and expensive queries -- centered "
        "on pg_stat_statements as the primary continuous instrumentation, plus guidance on "
        "configuring statement-level logging (log_min_duration_statement, auto_explain) through "
        "Aurora's DB parameter group model. This is durable observability infrastructure, not a "
        "one-off diagnostic pass: the goal is that the next slow-query incident starts with "
        "existing data to query, not with turning on instrumentation after the fact."
    ),
    symptoms=[
        "No active symptom -- this workflow is used to establish or audit standing query observability, not to investigate a specific slow query (see performance/slow-queries for that).",
        "An incident review discovers that the specific slow statement's history could not be reconstructed because pg_stat_statements had been reset, or logging was never capturing it.",
        "A new cluster or a new database within an existing cluster needs the same query-level observability the rest of the fleet already has.",
    ],
    business_impact=[
        "Without pg_stat_statements running continuously, every slow-query investigation starts from zero: no history of which statements are normally slow, so distinguishing 'normal for this workload' from 'new regression' after an incident already occurred is close to guesswork.",
        "log_min_duration_statement, correctly tuned, is often the only way to see complete text and exact parameters of an actually slow statement (pg_stat_statements normalizes and can truncate query text) -- without it, root-causing a specific slow occurrence can be impossible after the fact.",
        "auto_explain with timing enabled captures the *actual* execution plan a slow statement used in production, which is frequently different from what EXPLAIN produces when run manually afterward against a since-changed data distribution.",
    ],
    root_causes=[
        "Not a failure workflow -- this is about the presence and correctness of instrumentation, not a specific query problem.",
        "The most common gap this workflow closes: pg_stat_statements not enabled at all (it requires a parameter-group change and a reboot on Aurora, so it is sometimes deferred and forgotten), or enabled but with a query-text-store size/eviction setting too small for the workload's query diversity.",
        "log_min_duration_statement left at its default (disabled or very high) because logging every slow statement's full text has a real I/O and log-volume cost that was never explicitly budgeted for.",
    ],
    investigation_strategy=[
        "Confirm pg_stat_statements is installed and actively tracking (script 01 detects and reports if it is not).",
        "Establish the top-total-time and top-mean-time views as the two complementary rankings every review should check.",
        "Add the temp-file/I/O-heavy view to catch queries whose cost is memory/I/O pressure rather than raw latency.",
        "Decide and document the log_min_duration_statement threshold and auto_explain configuration for this cluster's parameter group, understanding the Aurora reboot/logging-volume tradeoffs first (script 04).",
        "Revisit the pg_stat_statements query-text-store sizing (pg_stat_statements.max) periodically -- a workload with high query-shape diversity (many distinct ad hoc or ORM-generated statements) can silently evict older, still-relevant entries.",
    ],
    prerequisites=[
        "Role membership in pg_monitor (or pg_read_all_stats), plus SELECT on pg_stat_statements once it is installed.",
        "pg_stat_statements in the Aurora DB cluster parameter group's shared_preload_libraries (requires a reboot to apply) and CREATE EXTENSION pg_stat_statements run in each database that needs it, both as change-managed actions outside this workflow's SQL scope.",
        "Agreement with the platform/logging team on the log volume budget before enabling verbose statement logging cluster-wide -- log_min_duration_statement set too low on a high-throughput exchange writer can itself become an I/O and log-ingestion cost problem.",
    ],
    interpretation_guide=[
        "Rank by total_exec_time to find where the database spends its aggregate time (a cheap statement executed millions of times can dominate); rank by mean_exec_time (with a minimum call-count filter) to find individually slow statements that may not yet be frequent enough to dominate the total.",
        "A statement's presence in the temp-file/I/O-heavy view alongside a merely moderate execution time is still worth investigating -- it is consuming memory/I/O capacity disproportionate to its apparent latency cost, and that capacity is shared with every other query on the instance.",
        "pg_stat_statements normalizes literal values out of query text (parameters become placeholders), which is exactly what allows similar statements to aggregate together -- but it also means the view alone cannot show which specific parameter value was slow; that is what log_min_duration_statement and auto_explain are for.",
        "All pg_stat_statements counters are cumulative since the last reset (extension creation, explicit pg_stat_statements_reset(), or an Aurora failover) -- always check whether a comparison period spans a reset before concluding a query got faster or slower.",
    ],
    remediation_immediate=[
        "This workflow builds standing observability; it does not remediate a specific slow query -- once a statement is identified, route to performance/slow-queries or query-optimization/analyze-query-plan for plan-level remediation.",
    ],
    remediation_short_term=[
        "If pg_stat_statements is not yet installed, schedule the parameter-group change and reboot, and treat the extension's creation as the starting point for this cluster's query-history baseline.",
        "If pg_stat_statements.max is undersized for this workload's query-shape diversity, raise it in the parameter group (also requires a reboot) rather than accepting silent eviction of older statement entries.",
    ],
    remediation_long_term=[
        "Establish a recurring (weekly or per-release) review of the top-total-time and top-mean-time views as a standing practice, not only a reactive one triggered by an incident.",
        "Feed the top-statement views into the dashboard layout proposed in dashboard-recommendations so query-level trends are visible continuously.",
    ],
    production_safety=[
        "The three read-only scripts in this workflow are strictly read-only and safe to run at any time, including during an active incident.",
        "pg_stat_statements itself adds a small, generally negligible per-query overhead for tracking; it is designed to run continuously in production and is not something to enable only temporarily.",
        "Enabling log_min_duration_statement or auto_explain (script 04) changes what gets written to the instance's logs and therefore has a real I/O and log-ingestion cost at a low threshold on a high-throughput writer -- read the runbook's guidance on choosing a threshold before applying it, and treat the change itself as a parameter-group change requiring the same review as any other.",
    ],
    escalation_criteria=[
        "pg_stat_statements is found to not be installed anywhere in the fleet -- this is a standing observability gap, not an incident, but should be treated as high-priority infrastructure work given how much it limits every future slow-query investigation.",
        "A statement responsible for a large share of total_exec_time on the order-placement, balance-check, withdrawal, or settlement path -- escalate to performance/slow-queries with this workflow's output attached.",
        "pg_stat_statements.max eviction is suspected (a previously-seen statement is missing from the current view with no reset having occurred) -- escalate to raise the setting before more history is lost.",
    ],
    related_issues=[
        "../postgres-metrics/README.md",
        "../performance-insights/README.md",
        "../wait-event-analysis/README.md",
        "../../performance/slow-queries/README.md",
        "../../query-optimization/analyze-query-plan/README.md",
        "../../query-optimization/query-plan-regression/README.md",
    ],
    aurora_notes=[
        "pg_stat_statements requires shared_preload_libraries to include it at the Aurora DB cluster parameter group level, which requires a reboot (and therefore a failover in a multi-instance cluster) to apply -- plan this like any other maintenance action, not as a quick same-session change.",
        "Aurora does not support ALTER SYSTEM for most parameters, including log_min_duration_statement and auto_explain settings -- these are configured through the DB cluster/instance parameter group (see script 04's runbook) and some require a reboot to take effect.",
        "An Aurora failover resets pg_stat_statements' accumulated counters on the promoted instance -- any 'this got faster/slower' comparison spanning a failover is comparing across a reset window and is not a valid conclusion on its own.",
        "Aurora's CloudWatch Logs integration is the mechanism for actually retrieving log-based output (log_min_duration_statement, auto_explain) from an Aurora instance -- there is no local filesystem log access the way there is on a self-managed server.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_top_statements_by_total_time",
        "Ranks normalized statements by cumulative execution time -- the primary 'where does the database spend its time' view.",
        _pgss_guarded(sb.pgss_top_by_total_time()),
        "This is the ranking to check first on a recurring cadence: total time (not mean time) determines aggregate capacity consumption, so a cheap, extremely frequent statement can legitimately outrank an individually slower but rare one. Save each review's output to compare against the next one and catch a statement whose share of total time is silently growing.",
        required_privileges=PG_MONITOR_PLUS_PGSS,
        prerequisites=PGSS_PREREQ,
        related_scripts="02_top_statements_by_mean_time.sql",
        table_purpose="Top statements by cumulative execution time (pg_stat_statements).",
    ),
    sql_script(
        "02", "02_top_statements_by_mean_time",
        "Ranks statements by mean execution time (restricted to a minimum call count) to find individually slow statements regardless of total volume.",
        _pgss_guarded(sb.pgss_top_by_mean_time()),
        "The minimum-calls filter keeps a single slow ad hoc/migration query from crowding out genuinely slow, recurring production statements. A high stddev_exec_time alongside a moderate mean suggests the statement's cost depends heavily on its parameters or on a data distribution that changes over time (a plan that is fast for common values and slow for rare ones), which total/mean time alone would not reveal.",
        required_privileges=PG_MONITOR_PLUS_PGSS,
        prerequisites=PGSS_PREREQ,
        related_scripts="03_temp_file_and_io_heavy_statements.sql",
        table_purpose="Top statements by mean execution time, minimum call count enforced (pg_stat_statements).",
    ),
    sql_script(
        "03", "03_temp_file_and_io_heavy_statements",
        "Ranks statements by temp file and shared-buffer I/O volume, surfacing memory/I/O pressure independent of raw latency.",
        _pgss_guarded(sb.pgss_temp_and_io_heavy()),
        "A statement here with only moderate mean_exec_time is still worth investigating: it is consuming memory (spilling to temp files) or I/O (high shared_blks_read) disproportionate to its apparent cost, and that capacity is shared with every other concurrent query on the instance. This view frequently surfaces the root cause behind a work_mem or statistics-staleness finding elsewhere in this repository.",
        required_privileges=PG_MONITOR_PLUS_PGSS,
        prerequisites=PGSS_PREREQ,
        related_scripts="04_configuring_log_min_duration_and_auto_explain.md",
        table_purpose="Top statements by temp file and shared-buffer I/O volume (pg_stat_statements).",
    ),
    md_script(
        "04", "04_configuring_log_min_duration_and_auto_explain",
        "Runbook for configuring log_min_duration_statement and auto_explain through Aurora's DB parameter group model.",
        """
## Why pg_stat_statements alone is not enough

pg_stat_statements aggregates by normalized query shape and does not retain
the exact parameter values or the actual execution plan used for a specific
slow occurrence. `log_min_duration_statement` and `auto_explain` fill that
gap by logging the full statement (with parameters) and, optionally, the
real execution plan, whenever a statement exceeds a duration threshold.

## Aurora's parameter-group model (read before changing anything)

Aurora PostgreSQL does not support `ALTER SYSTEM` for most parameters,
including these logging settings. They are configured through the DB
cluster parameter group (cluster-wide defaults) or DB instance parameter
group (writer/reader-specific overrides), applied via the AWS Console, CLI,
or infrastructure-as-code -- never through a SQL session:

```
aws rds modify-db-cluster-parameter-group \\
  --db-cluster-parameter-group-name <parameter-group-name> \\
  --parameters "ParameterName=log_min_duration_statement,ParameterValue=1000,ApplyMethod=immediate"
```

`log_min_duration_statement` and `auto_explain.log_min_duration` typically
apply without a reboot (dynamic parameters); confirm the specific
parameter's `ApplyType` in `describe-db-cluster-parameters` before assuming
so, since this can change between engine versions.

## Choosing a threshold

Start conservative on a high-throughput exchange writer: a threshold set
far below the workload's normal latency profile generates log volume
proportional to *most* queries, which is itself an I/O and log-ingestion
cost and can obscure the genuinely slow outliers in noise. A reasonable
starting point is the current p99 latency for the busiest transactional
path, reviewed and tightened over time as the log volume proves manageable.

## Enabling auto_explain for real execution plans

`auto_explain` requires `shared_preload_libraries` to include it at the
cluster parameter group level (a reboot-requiring change, unlike the
duration threshold itself). Once loaded, enable it with:

```
aws rds modify-db-cluster-parameter-group \\
  --db-cluster-parameter-group-name <parameter-group-name> \\
  --parameters "ParameterName=auto_explain.log_min_duration,ParameterValue=1000,ApplyMethod=immediate" \\
                "ParameterName=auto_explain.log_analyze,ParameterValue=1,ApplyMethod=immediate"
```

`auto_explain.log_analyze` runs the equivalent of `EXPLAIN (ANALYZE)` for
every statement crossing the threshold, which adds real overhead to those
specific statements (timing instrumentation, not just plan capture) --
enable it deliberately, at a threshold high enough that it only fires for
statements already confirmed slow, not as a blanket setting.

## Retrieving the logged output

Aurora ships PostgreSQL log output to CloudWatch Logs (the log group named
for the DB instance) -- there is no local filesystem log access. Query it
via CloudWatch Logs Insights, or export it to the same pipeline the rest of
this repository's observability recommendations (dashboard-recommendations)
assume.
""".strip("\n"),
        "Follow this runbook when standing up statement-level logging for the first time, or when tuning an existing threshold that is producing too much or too little log volume. None of the AWS CLI examples here are SQL statements this repository executes -- they are documented AWS-side change steps for the operator to review and run deliberately.",
        safety="LOW RISK WRITE (Aurora DB parameter group change; log_min_duration_statement typically applies without a reboot, auto_explain's shared_preload_libraries entry requires one -- see runbook)",
        expected_impact="Increases log volume and CloudWatch Logs ingestion cost proportional to the chosen threshold; auto_explain with log_analyze adds real per-statement overhead for statements that cross the threshold.",
        required_privileges="IAM permission to modify the DB cluster/instance parameter group (rds:ModifyDBClusterParameterGroup or console equivalent); no PostgreSQL role required for the parameter-group steps.",
        prerequisites="Agreement with the platform/logging team on the log volume budget before applying a low threshold cluster-wide.",
        execution_location=ANY_INSTANCE,
        expected_runtime="Minutes to apply; dynamic parameters take effect without a restart, auto_explain's preload-library entry requires a reboot the first time it is added.",
        related_scripts="../../performance/slow-queries/README.md",
        table_purpose="Runbook: configure log_min_duration_statement / auto_explain via the Aurora parameter group.",
    ),
]

# ---------------------------------------------------------------------------
# wait-event-analysis
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="wait-event-analysis",
    title="Wait Event Analysis",
    summary=(
        "A deep dive on pg_stat_activity's wait_event_type / wait_event columns -- what each "
        "wait event category actually means, how to read the aggregated and per-session views, "
        "and how this same taxonomy is what Performance Insights uses to color its DB load chart. "
        "Wait events are the most direct answer PostgreSQL can give to 'what is this session "
        "waiting for right now', and reading them correctly is usually faster than guessing from "
        "symptoms alone."
    ),
    symptoms=[
        "Sessions are active but query latency is elevated with no single obvious cause -- wait event analysis is the fastest way to classify whether the cause is CPU, locking, I/O, or something else entirely.",
        "Performance Insights' DB load view shows a dominant wait event and the corresponding live session/query detail is needed to act on it.",
        "A specific wait_event value is unfamiliar and its meaning needs to be confirmed before deciding whether it indicates a problem.",
    ],
    business_impact=[
        "Correctly classifying a wait event in the first minute of an investigation (Lock vs. IO vs. IPC vs. CPU) sends the on-call DBA directly to the right dedicated workflow instead of a broad, slower elimination process across every possible cause.",
        "Some wait events (Lock, IPC) directly indicate that other sessions are being blocked right now -- on an exchange's order or ledger path, recognizing this immediately is the difference between a two-minute fix and a cascading pool-exhaustion incident.",
        "Other wait events (Client, most of Activity) are entirely expected and never indicate a database-side problem -- misreading these as a database issue wastes investigation time that should go toward the application or network layer instead.",
    ],
    root_causes=[
        "Not a failure workflow -- this documents how to interpret a signal, not a specific failure mode.",
        "The most common misinterpretation this workflow corrects: treating any non-null wait_event as inherently a problem, when several wait event types (Client, Activity) are the fully expected, healthy state for a connection-pooled idle or background-worker session.",
    ],
    investigation_strategy=[
        "Get the aggregated wait event summary first, to see the overall shape of current load before looking at any individual session.",
        "Break the aggregation down further by state (active vs. idle-in-transaction vs. idle) to separate genuine contention from expected idle waiting.",
        "Drill into per-session detail for the specific wait_event_type/wait_event combination that dominates, to identify the exact sessions and queries responsible.",
        "Use the wait event type reference to confirm the meaning of any specific wait_event value before deciding whether it is actionable.",
        "Cross-reference against Performance Insights' DB load view (performance-insights) for the same classification over a longer historical window than a live snapshot can show.",
    ],
    prerequisites=[
        "Role membership in pg_monitor (or pg_read_all_stats).",
        "Familiarity with this workflow's wait event type reference (script 04), especially before an incident, since reading it for the first time under pressure is slower than having it already understood.",
    ],
    interpretation_guide=[
        "wait_event_type is the broad category (Lock, LWLock, BufferPin, Activity, Client, Extension, IPC, IO, Timeout); wait_event is the specific instance within that category -- always read both together, since the same wait_event name can theoretically exist informationally differently across versions while the type rarely does.",
        "Lock: the session is waiting on a heavyweight lock (row, table, or object level) held by another session -- this is directly actionable via concurrency-and-locking/blocked-queries and blocking_sessions_detail-style joins, and is never the expected steady state for more than a brief moment.",
        "LWLock and BufferPin: internal PostgreSQL synchronization primitives -- occasional brief occurrences are normal; a sustained concentration of sessions here usually indicates contention on a specific internal structure (e.g. a hot buffer) rather than an application-level lock, and needs a targeted investigation rather than the standard blocking-session approach.",
        "IO: the session is waiting on a storage read/write -- on Aurora this specifically means a round trip to the distributed storage layer, and a sustained concentration here is the SQL-level signal that corresponds to elevated DiskQueueDepth/VolumeReadIOPs in CloudWatch.",
        "IPC: inter-process communication, commonly parallel query workers waiting on each other, or a session waiting on a checkpoint/vacuum coordination point -- usually benign and self-resolving, but a sustained large count warrants checking what parallel or maintenance operations are in flight.",
        "Client and most of Activity: the session is waiting on the client application (a query result already sent, or the connection is simply idle) -- this is the expected state for the majority of connections in a healthy, pooled application at any given moment and is not itself a finding.",
        "Timeout: the session is in a deliberate sleep (e.g. pg_sleep, or a background process on its configured interval) -- confirm which specific wait_event this is before assuming it means anything is wrong.",
    ],
    remediation_immediate=[
        "This workflow is diagnostic, not remedial -- once the dominant wait event and responsible sessions are identified, route to the workflow that owns that specific wait event category (see Related Issues).",
    ],
    remediation_short_term=[
        "For a Lock-dominated finding, resolve the blocking session per concurrency-and-locking/blocked-queries rather than treating the wait event alone as sufficient diagnosis.",
        "For an IO-dominated finding, corroborate against CloudWatch's storage-layer metrics (cloudwatch) before concluding the storage layer itself is the bottleneck versus a specific query's access pattern (tables-and-indexes/sequential-scan-investigation).",
    ],
    remediation_long_term=[
        "Add wait-event distribution to the standing dashboard (dashboard-recommendations) so a shift in the normal mix is visible as a trend, not only discovered during an active incident.",
        "Use Performance Insights' longer retention (performance-insights) to establish this cluster's normal wait-event baseline by time of day/week, so a live snapshot can be judged against an actual expectation rather than intuition.",
    ],
    production_safety=[
        "Every script in this workflow is strictly read-only and safe to run at any time, including during a severe incident -- these are exactly the queries to run first when load is elevated and the cause is unknown.",
        "The per-session detail script includes query text, which may include sensitive literal values if pg_stat_activity is configured to show full statements -- handle output with the same care as any other query-text-containing diagnostic in this repository.",
    ],
    escalation_criteria=[
        "Lock wait events dominate for more than a few minutes -- escalate immediately to concurrency-and-locking/lock-contention or blocked-queries; on wallet/ledger tables this risks a financial-operation-visible delay.",
        "IO wait events dominate with no corresponding CloudWatch storage-layer metric explanation -- escalate to performance/high-iops.",
        "A wait_event value not covered by the reference in script 04 appears prominently -- confirm its meaning against the current PostgreSQL 17 documentation before dismissing or escalating it, since new wait events are occasionally added between minor versions.",
    ],
    related_issues=[
        "../performance-insights/README.md",
        "../postgres-metrics/README.md",
        "../../concurrency-and-locking/blocked-queries/README.md",
        "../../concurrency-and-locking/lock-contention/README.md",
        "../../performance/high-iops/README.md",
        "../../performance/high-database-load/README.md",
    ],
    aurora_notes=[
        "The wait_event_type/wait_event taxonomy on Aurora PostgreSQL is the same one standard community PostgreSQL 17 exposes -- Aurora does not remap or rename these values, which is exactly why Performance Insights' wait-event coloring lines up directly with a live pg_stat_activity query.",
        "IO wait events on Aurora represent a round trip to the distributed storage layer rather than a local disk read -- a given IO wait event's latency profile can differ meaningfully from the same wait event on self-managed PostgreSQL running against local NVMe storage, so do not assume self-managed PostgreSQL latency expectations transfer directly.",
        "pg_wait_events (joined in scripts 01 and 03 for plain-language descriptions) is a standard PostgreSQL 17 catalog view and is fully available on Aurora.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_current_wait_event_summary",
        "Aggregates current backends by wait event type/name, joined to pg_wait_events for a plain-language description.",
        sb.wait_events_summary(),
        "Read this as the overall shape of current load before drilling into anything specific. A healthy exchange writer under normal load shows mostly Client/Activity (expected idle) with a small amount of CPU-bound activity; any large concentration in Lock, IO, or IPC is the signal to drill into script 02 or 03 immediately.",
        related_scripts="02_wait_event_contention_by_type_and_state.sql",
        table_purpose="Current backend counts by wait event type/name, with description.",
    ),
    sql_script(
        "02", "02_wait_event_contention_by_type_and_state",
        "Breaks wait events down further by session state, to separate genuine contention from expected idle waiting.",
        sb.connection_contention_by_wait_event(),
        "Cross-tabulating by state distinguishes 'many sessions waiting on Client because they are idle between requests' (normal) from 'many active sessions waiting on Lock' (a genuine contention finding). longest_time_in_state flags the single longest-waiting session in each group, which is usually the most useful starting point for the per-session drill-down in script 03.",
        related_scripts="03_per_session_wait_event_detail.sql",
        table_purpose="Wait event counts broken down by session state.",
    ),
    sql_script(
        "03", "03_per_session_wait_event_detail",
        "Row-per-session detail for every backend currently registering a wait event, with plain-language description and query text.",
        """
-- Row-per-session detail for every backend currently registering a wait
-- event, joined to pg_wait_events for a plain-language description. Use
-- this once the aggregated counts in scripts 01/02 show a wait_event_type
-- worth investigating and the exact responsible sessions/queries are
-- needed.
SELECT
    a.pid,
    a.usename,
    a.datname,
    a.wait_event_type,
    a.wait_event,
    we.description,
    a.state,
    now() - a.state_change                                        AS time_in_current_wait,
    left(a.query, 160)                                             AS query_snippet
FROM pg_stat_activity a
LEFT JOIN pg_wait_events we
       ON we.type = a.wait_event_type
      AND we.name = a.wait_event
WHERE a.pid <> pg_backend_pid()
  AND a.wait_event IS NOT NULL
ORDER BY time_in_current_wait DESC NULLS LAST;
""".strip("\n"),
        "The sessions with the longest time_in_current_wait are the ones to focus on first. For a Lock wait_event_type, cross-reference these pids against concurrency-and-locking/blocked-queries' blocking-session detail to find who is actually holding the lock this session is waiting for -- this view shows the waiter, not the blocker.",
        related_scripts="04_wait_event_type_reference.md, ../../concurrency-and-locking/blocked-queries/README.md",
        table_purpose="Per-session wait event detail with description and query snippet.",
    ),
    md_script(
        "04", "04_wait_event_type_reference",
        "Reference guide to each wait_event_type category's meaning, typical causes, and whether it is normally actionable.",
        """
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
""".strip("\n"),
        "Use this table to quickly classify whether a wait_event_type found in scripts 01-03 is expected background noise or requires immediate investigation, without needing to look it up externally during an incident.",
        safety=READ_ONLY + " (reference documentation only; no SQL statements are executed by this file)",
        expected_impact=REFERENCE_DOC_IMPACT,
        required_privileges=PG_MONITOR,
        prerequisites="None to read this reference.",
        execution_location=ANY_INSTANCE,
        expected_runtime="A few minutes to read.",
        related_scripts="../performance-insights/README.md",
        table_purpose="Reference: wait_event_type meanings and whether each is normally actionable.",
    ),
]

# ---------------------------------------------------------------------------
# dashboard-recommendations
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="dashboard-recommendations",
    title="Baseline Aurora PostgreSQL DBA Dashboard Recommendations",
    summary=(
        "A proposed baseline layout for a team building its own always-on Grafana/CloudWatch "
        "dashboard for an Aurora PostgreSQL fleet, grouping the signals from postgres-metrics, "
        "performance-insights, cloudwatch, slow-query-observability, and wait-event-analysis into "
        "a coherent set of panels. This workflow is primarily documentation: the goal is a "
        "concrete starting layout a platform team can implement immediately, plus a single-row "
        "query that can back a simple 'cluster at a glance' panel without any other tooling."
    ),
    symptoms=[
        "No active symptom -- this workflow is used when standing up a new dashboard, or auditing an existing one against a documented baseline.",
        "An incident review finds that a signal which would have shown the problem developing was being collected (per postgres-metrics) but was never actually placed on a dashboard anyone looks at regularly.",
        "Multiple teams each maintain their own ad hoc dashboard with inconsistent coverage, and a shared baseline is needed.",
    ],
    business_impact=[
        "A dashboard that is actually watched continuously catches the same slow-moving conditions (connection creep, vacuum debt, XID age, reader lag) that daily-health-check catches, but earlier and without requiring someone to remember to run a check.",
        "A well-organized dashboard shortens every future incident's first few minutes, since the on-call engineer starts from an already-visible picture of load, replication, and vacuum health instead of reconstructing it live under time pressure.",
        "Consistent dashboard coverage across every cluster in the fleet means an engineer on-call for a cluster they do not normally own can orient just as quickly as the cluster's regular owner.",
    ],
    root_causes=[
        "Not a failure workflow -- this is a documentation/planning workflow proposing a dashboard structure.",
        "The most common gap this closes: a dashboard built early and never revisited, covering only the CloudWatch-visible basics (CPU, connections) while database-internal signals (vacuum, XID age, query-level stats, wait events) are collected but never actually surfaced anywhere a human looks routinely.",
    ],
    investigation_strategy=[
        "Inventory what is already on the existing dashboard (if any) against the panel groups proposed below.",
        "For each proposed panel group, identify the specific CloudWatch metric and/or SQL script from this repository that backs it.",
        "Prioritize adding the panel groups this cluster's own incident history shows would have helped most (see database-health/comprehensive-health-check for how to establish that history).",
        "Use the single-row snapshot query as a quick starting data source for a 'cluster at a glance' panel while the fuller per-panel queries are being wired up individually.",
    ],
    prerequisites=[
        "A dashboarding tool already in use or planned (Grafana with a PostgreSQL and/or CloudWatch data source, or CloudWatch dashboards directly).",
        "Role membership in pg_monitor (or pg_read_all_stats) for the dashboard's PostgreSQL data source connection.",
        "The individual metrics and scripts referenced from postgres-metrics, cloudwatch, performance-insights, slow-query-observability, and wait-event-analysis -- this workflow organizes them, it does not redefine them.",
    ],
    interpretation_guide=[
        "This is a starting layout, not a mandate -- adapt panel groupings to this cluster's actual failure history and the platform team's existing tooling conventions.",
        "Panels backed by cumulative PostgreSQL counters (throughput, cache hit ratio, WAL) need the dashboard tool to compute a rate/derivative between samples -- wiring the raw cumulative value directly into a stat panel without a rate calculation will show a number that only ever goes up.",
        "Panels backed by CloudWatch metrics are already rate/gauge-appropriate as published; panels backed by this repository's SQL scripts are point-in-time snapshots unless the collector polls them on an interval and the dashboard tool computes the rate itself.",
        "Group panels by operational question ('are we out of headroom', 'is replication healthy', 'is vacuum keeping up') rather than by source system (SQL vs. CloudWatch) -- an on-call engineer during an incident thinks in terms of the question, not the data source.",
    ],
    remediation_immediate=[
        "This workflow is planning/documentation -- it has no immediate remediation of its own.",
    ],
    remediation_short_term=[
        "Add the single-row snapshot query (script 01) as a quick stat-panel data source for any panel group not yet wired up individually, then replace it with the fuller per-panel queries as time allows.",
        "Close the single highest-value gap identified during the dashboard audit first (typically vacuum/XID visibility or replication lag, per the incident-history findings from database-health/comprehensive-health-check).",
    ],
    remediation_long_term=[
        "Standardize this dashboard layout across every cluster in the fleet via infrastructure-as-code (Grafana provisioning, or a shared CloudWatch dashboard template), so coverage does not depend on which team built which cluster's dashboard.",
        "Revisit the panel groupings periodically against the escalation criteria in each source workflow, since a threshold that made sense at last year's trading volume may no longer be the right line to draw.",
    ],
    production_safety=[
        "The one SQL script in this workflow is strictly read-only and inexpensive; safe to poll on a short interval from a dashboard collector.",
        "This workflow recommends dashboard structure only -- it does not itself grant any permission or provision any AWS resource; implementing it follows whatever change process the platform team already uses for dashboard/infrastructure-as-code changes.",
    ],
    escalation_criteria=[
        "This workflow does not define escalation criteria of its own -- each panel group's escalation threshold is inherited from the workflow that owns that signal (see Related Issues and each panel's source workflow).",
    ],
    related_issues=[
        "../postgres-metrics/README.md",
        "../cloudwatch/README.md",
        "../performance-insights/README.md",
        "../slow-query-observability/README.md",
        "../wait-event-analysis/README.md",
        "../../database-health/comprehensive-health-check/README.md",
        "../../database-health/daily-health-check/README.md",
    ],
    aurora_notes=[
        "A dashboard mixing CloudWatch (instance/cluster-level) and SQL-sourced (per-connection) panels should clearly label which instance (writer vs. a specific reader) each SQL-sourced panel reflects, since pg_stat_activity and most catalog views are per-instance, while several CloudWatch metrics (VolumeBytesUsed, AuroraReplicaLag) are cluster- or per-reader-scoped in ways that do not map one-to-one onto a single SQL connection.",
        "Panels sourced from cumulative PostgreSQL counters reset on an Aurora failover -- annotate the dashboard with failover events (available as a CloudWatch event) so a sudden drop in a rate panel immediately after a failover is not mistaken for an actual workload decrease.",
        "Aurora reader instances can be added or removed as part of normal autoscaling -- a dashboard's per-reader panels should be built to handle a changing instance count over time rather than assuming a fixed set of reader identifiers.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_single_row_dashboard_snapshot",
        "Single-row, dashboard-panel-friendly snapshot of the handful of metrics most teams put on a 'cluster at a glance' stat panel.",
        """
-- Single-row, dashboard-panel-friendly snapshot combining the handful of
-- metrics most teams put on a "cluster at a glance" Grafana stat panel.
-- Point a scheduled collector (or a Grafana PostgreSQL data source panel
-- set to table/stat visualization) at this query directly -- it
-- deliberately returns exactly one row so it renders cleanly without any
-- client-side aggregation.
SELECT
    now()                                                                      AS captured_at,
    (SELECT count(*) FROM pg_stat_activity)                                    AS current_connections,
    round(
        100.0 * (SELECT count(*) FROM pg_stat_activity) /
        NULLIF((SELECT setting::numeric FROM pg_settings WHERE name = 'max_connections'), 0),
        2
    )                                                                          AS pct_connections_used,
    (SELECT count(*) FROM pg_stat_activity WHERE state = 'idle in transaction') AS idle_in_transaction_count,
    (SELECT max(now() - xact_start) FROM pg_stat_activity WHERE xact_start IS NOT NULL) AS longest_open_txn,
    round(
        100.0 * sum(blks_hit) / NULLIF(sum(blks_hit) + sum(blks_read), 0), 2
    )                                                                          AS cache_hit_pct,
    sum(deadlocks)                                                             AS deadlocks_since_reset,
    (SELECT round(max(100.0 * age(datfrozenxid) /
         (SELECT setting::numeric FROM pg_settings WHERE name = 'autovacuum_freeze_max_age')), 2)
     FROM pg_database WHERE datallowconn)                                      AS worst_pct_of_freeze_max_age
FROM pg_stat_database
WHERE datname IS NOT NULL;
""".strip("\n"),
        "Wire each column into its own stat panel, or the whole row into a single table panel, as a quick-start dashboard while the fuller per-signal panels from postgres-metrics/cloudwatch/wait-event-analysis are being built out individually. worst_pct_of_freeze_max_age and longest_open_txn are the two values most worth an alert threshold immediately, since both indicate slow-moving conditions that are easy to miss without a standing panel.",
        execution_location=WRITER_PREFERRED,
        related_scripts="02_baseline_dashboard_layout_recommendations.md",
        table_purpose="Single-row cluster-at-a-glance snapshot for a quick-start dashboard panel.",
    ),
    md_script(
        "02", "02_baseline_dashboard_layout_recommendations",
        "Proposed baseline panel layout for a Grafana/CloudWatch Aurora PostgreSQL DBA dashboard, grouped by operational question.",
        """
## Recommended panel groups

Organize the dashboard by operational question, not by data source. For
each group below, the "Source" column names the workflow/script in this
repository (or the CloudWatch metric) that backs it.

### 1. Connections & load

| Panel | Source |
| --- | --- |
| Current connections vs. `max_connections` (gauge) | `postgres-metrics` script 01, or CloudWatch `DatabaseConnections` |
| Connections by application/user (table) | `postgres-metrics` script 01 (`connections_by_application_and_user`-style query) |
| Wait event distribution (stacked time series) | `wait-event-analysis` script 01, or Performance Insights DB load |
| Longest open transaction (stat) | This workflow's script 01, or `database-health/daily-health-check` |

### 2. Replication & lag

| Panel | Source |
| --- | --- |
| Aurora reader lag per reader (time series) | `cloudwatch` script 02 (`aurora_replica_status()`), or CloudWatch `AuroraReplicaLag` |
| Replication slot WAL retention (table) | `database-health/capacity-health-check` script 05 |

### 3. Vacuum & XID age

| Panel | Source |
| --- | --- |
| Worst `pct_of_freeze_max_age` across databases (gauge, alert threshold) | This workflow's script 01, or `database-health/daily-health-check` |
| Dead tuple ratio, top tables (table) | `postgres-metrics` script 03 |
| Active autovacuum workers (table) | `database-health/comprehensive-health-check` script 08 |

### 4. Query performance

| Panel | Source |
| --- | --- |
| Top statements by total time (table, refreshed periodically) | `slow-query-observability` script 01 |
| Top statements by mean time (table) | `slow-query-observability` script 02 |
| DB load by SQL (Performance Insights embed or equivalent) | `performance-insights` script 02 |

### 5. I/O & checkpoints

| Panel | Source |
| --- | --- |
| Checkpoint pct forced vs. scheduled (time series) | `postgres-metrics` script 04, or CloudWatch `DiskQueueDepth` |
| pg_stat_io read/write volume by backend type (table) | `postgres-metrics` script 04 |
| CloudWatch Volume IOPS (time series) | CloudWatch `VolumeReadIOPs` / `VolumeWriteIOPs` |

### 6. Storage & capacity

| Panel | Source |
| --- | --- |
| Database and largest-table sizes (table) | `database-health/capacity-health-check` script 01 |
| CloudWatch storage volume trend (time series) | CloudWatch `VolumeBytesUsed` |
| Temp file volume (time series) | `postgres-metrics` script 02, or `database-health/capacity-health-check` script 06 |

## Implementation notes

* Prefer a single shared dashboard definition (Grafana provisioning-as-code,
  or a shared CloudWatch dashboard template) applied across every cluster
  in the fleet, rather than one dashboard per cluster maintained by hand.
* Annotate the dashboard with Aurora failover events so a reset in
  cumulative counters is visually explained rather than misread as an
  improvement.
* Start every new cluster with this baseline layout before it goes to
  production, rather than treating dashboarding as a follow-up task after
  the first incident.
""".strip("\n"),
        "Use this as the starting checklist when building a new dashboard or auditing an existing one -- each row names the exact script/metric in this repository (or CloudWatch) that backs it, so implementation is a direct lookup rather than a design exercise.",
        safety="INFORMATIONAL -- NO SQL EXECUTED, DASHBOARD/ALERTING DESIGN GUIDANCE ONLY",
        expected_impact=REFERENCE_DOC_IMPACT,
        required_privileges=PG_MONITOR,
        prerequisites="None to read this reference. Each panel's underlying script/metric has its own prerequisites.",
        execution_location=ANY_INSTANCE,
        expected_runtime="An implementation planning exercise; not a runtime-bound script.",
        related_scripts="01_single_row_dashboard_snapshot.sql",
        table_purpose="Reference: recommended baseline dashboard panel layout, grouped by operational question.",
    ),
]
