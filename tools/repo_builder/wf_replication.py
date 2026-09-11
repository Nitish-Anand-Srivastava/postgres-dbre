"""Workflow definitions: replication-and-ha/ category (7 issue directories).

Every workflow in this category is careful to distinguish Aurora's
storage-layer replica architecture from standard PostgreSQL streaming
replication -- pg_stat_replication does NOT show Aurora reader instances.
"""
from __future__ import annotations

from typing import List

from . import sql_blocks as sb
from .helpers import ANY_INSTANCE, PG_MONITOR, WRITER_ONLY, md_script, sql_script
from .model import Workflow

CATEGORY_SLUG = "replication-and-ha"
CATEGORY_TITLE = "Replication and High Availability"


def _wf(**kwargs) -> Workflow:
    kwargs.setdefault("category_slug", CATEGORY_SLUG)
    kwargs.setdefault("category_title", CATEGORY_TITLE)
    return Workflow(**kwargs)


WORKFLOWS: List[Workflow] = []

WORKFLOWS.append(_wf(
    slug="replication-lag",
    title="Replication Lag",
    summary="Investigates elevated replication lag -- either Aurora's native storage-layer reader lag, or standard PostgreSQL streaming/logical replication lag to an external consumer -- and helps distinguish the two, since they are measured and caused differently.",
    symptoms=["Application reading from a reader endpoint sees stale data relative to a recent write.", "CloudWatch AuroraReplicaLag metric elevated.", "An external logical replication subscriber (CDC, DMS) falling further behind."],
    business_impact=["Elevated reader lag directly risks read-after-write consistency bugs for any feature relying on reader-endpoint routing (e.g. reading an order immediately after placing it) -- a correctness risk, not just a performance one, in a financial platform."],
    root_causes=["High write/WAL volume on the writer outpacing the reader's redo-apply rate.", "A long-running query on the reader itself blocking redo application (Aurora readers can experience apply delay from local query conflicts, similar in spirit to standard PostgreSQL recovery conflicts).", "Reader instance under-provisioned (smaller instance class) relative to the writer's write rate.", "For external logical replication: the subscriber itself is slow/down, or a network issue between publisher and subscriber."],
    investigation_strategy=["Confirm which kind of lag is being observed: Aurora reader lag (use aurora_replica_status()) vs. standard streaming/logical replication lag (use pg_stat_replication on the writer).", "Check current WAL generation rate on the writer as a likely driver of reader lag.", "Check for long-running queries on the specific lagging reader.", "For external logical replication, check replication slot status for the specific subscriber."],
    prerequisites=["pg_monitor role membership on both writer and reader instances."],
    interpretation_guide=["Aurora reader lag (from aurora_replica_status()) and standard PostgreSQL pg_stat_replication lag measure fundamentally different things and are not interchangeable -- do not use pg_stat_replication to explain Aurora reader lag; it will not show Aurora readers at all."],
    remediation_immediate=["If a specific long-running query on the reader is blocking redo application, consider cancelling it after confirming impact (see incident-response/runaway-query for safety guidance, applied to the reader context)."],
    remediation_short_term=["Reduce WAL-heavy write patterns identified via performance/high-iops's pgss_wal_heavy script.", "Consider a larger reader instance class if consistently under-provisioned relative to write volume."],
    remediation_long_term=["For features requiring strict read-after-write consistency, route those specific reads to the writer endpoint rather than relying on eventual reader consistency, or implement application-level read-your-writes handling (e.g. a short-lived cache of just-written data)."],
    production_safety=["All investigation scripts are read-only."],
    escalation_criteria=["Reader lag remains elevated with no identifiable query-level or WAL-volume cause -- open an AWS Support case, since this may indicate an Aurora storage-layer issue."],
    related_issues=["../reader-lag-investigation/README.md", "../reader-performance/README.md", "../../performance/high-iops/README.md"],
    aurora_notes=[
        "Aurora readers share the same underlying distributed storage volume as the writer and receive redo log records through Aurora's internal storage-layer replication mechanism -- they do NOT stream WAL from the writer via standard PostgreSQL physical replication, so pg_stat_replication on the writer will show NO rows for Aurora reader instances even when readers exist and are healthy.",
        "Use `aurora_replica_status()` (callable from any instance in the cluster) or the CloudWatch `AuroraReplicaLag`/`AuroraReplicaLagMaximum`/`AuroraReplicaLagMinimum` metrics as the authoritative source for Aurora reader lag.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_aurora_native_replica_lag", "Checks Aurora's native cluster-wide replica lag via the Aurora-specific function -- the correct source for reader lag on Aurora.",
               sb.aurora_replica_status(),
               "This reflects genuine Aurora storage-layer replication lag, not standard PostgreSQL streaming replication -- use this, not pg_stat_replication, to assess Aurora reader staleness.",
               related_scripts="02_standard_streaming_replication.sql"),
    sql_script("02", "02_standard_streaming_replication", "Checks standard PostgreSQL streaming replication status from the writer, for any external physical/logical replica or CDC consumer (NOT Aurora readers).",
               sb.standard_streaming_replication_status(),
               "An empty result here is completely normal on Aurora even with healthy readers -- it only shows genuine external streaming consumers. Do not interpret an empty result as 'no replicas exist'.",
               execution_location=WRITER_ONLY,
               related_scripts="03_writer_wal_generation.sql"),
    sql_script("03", "03_writer_wal_generation", "Checks current WAL generation rate on the writer, the primary driver of reader apply lag under high write volume.",
               sb.wal_activity(),
               "On Aurora PostgreSQL (verified through 17.7) this returns a single NOT AVAILABLE / guidance row instead of querying pg_stat_wal, since Aurora does not implement the pg_stat_get_wal() function backing that view -- use the CloudWatch or Performance Insights metrics named in the guidance row instead. On standard/self-managed PostgreSQL, compare wal_bytes across two snapshots to compute a rate; a high sustained WAL generation rate is the most common root cause of elevated reader apply lag.",
               execution_location=WRITER_ONLY,
               related_scripts="04_reader_side_long_queries.sql"),
    sql_script("04", "04_reader_side_long_queries", "Checks for long-running queries on the specific lagging reader instance that could be delaying redo application.",
               sb.active_long_running_queries(),
               "Run this connected directly to the lagging reader instance (not the writer or cluster endpoint) -- a long analytical query on the reader can itself delay how quickly it applies incoming redo.",
               execution_location="Reader instance specifically (connect directly to the lagging reader, not the cluster/reader load-balanced endpoint)",
               related_scripts="../reader-lag-investigation/README.md"),
]

WORKFLOWS.append(_wf(
    slug="reader-performance",
    title="Reader Instance Performance",
    summary="Investigates performance issues specific to an Aurora reader instance -- distinct from writer performance workflows, since readers have their own independent buffer cache, connection pool, and query load.",
    symptoms=["Read-only queries routed to a reader endpoint are slow, while the writer performs normally.", "One specific reader in a multi-reader cluster underperforms relative to its siblings."],
    business_impact=["Reader performance issues directly degrade any read-heavy, latency-sensitive feature deliberately offloaded to readers (market data display, order history, balance lookups) without necessarily showing up in writer-side monitoring."],
    root_causes=["The reader instance is a smaller instance class than the writer and is undersized for the read traffic routed to it.", "Reader-specific cold cache after a recent reboot/failover-related promotion.", "An uneven query router sending disproportionate traffic to one specific reader.", "Elevated reader lag itself causing query-side waits on recovery conflict resolution."],
    investigation_strategy=["Confirm which specific reader is affected and its instance class.", "Check its buffer cache hit ratio and current session/query load directly.", "Check its replica lag, since very high lag can itself cause query delays."],
    prerequisites=["Direct connection access to the specific reader instance (not just the reader load-balanced endpoint) to isolate a single-reader issue."],
    interpretation_guide=["If all readers in the cluster show the issue equally, suspect a cluster-wide cause (write volume, lag) rather than an instance-specific one; if only one reader is affected, suspect instance-specific factors (recent restart, an uneven query router, or a hardware-level AWS issue worth a support case)."],
    remediation_immediate=["Route traffic away from a specifically underperforming reader if your query router/application supports per-instance routing."],
    remediation_short_term=["Scale the underperforming reader to match the others' instance class if it was provisioned smaller."],
    remediation_long_term=["Ensure the reader fleet is sized and load-balanced appropriately for the read traffic volume (see storage-and-capacity/capacity-forecasting)."],
    production_safety=["Investigation scripts are read-only."],
    escalation_criteria=["A single reader underperforms with no explainable cause (matching instance class, matching lag, matching query load) -- open an AWS Support case for a possible instance-level hardware issue."],
    related_issues=["../replication-lag/README.md", "../writer-reader-imbalance/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_reader_cache_and_load", "Checks buffer cache hit ratio and current session load directly on the specific reader instance.",
               """
-- Buffer cache hit ratio and active session count for the CURRENT
-- connection's database -- run this connected directly to the specific
-- reader instance under investigation, not the load-balanced reader
-- endpoint, to isolate its individual state.
SELECT
    (SELECT round(100.0 * blks_hit / NULLIF(blks_hit + blks_read, 0), 2)
     FROM pg_stat_database WHERE datname = current_database())          AS cache_hit_ratio_pct,
    (SELECT count(*) FROM pg_stat_activity WHERE state = 'active')      AS active_sessions,
    (SELECT count(*) FROM pg_stat_activity)                             AS total_sessions,
    pg_is_in_recovery()                                                 AS confirmed_reader;
""".strip("\n"),
               "confirmed_reader should be true; a low cache_hit_ratio_pct on this specific reader relative to its siblings points to a cold-cache or under-provisioned-instance-class issue for this instance specifically.",
               execution_location="Reader instance specifically",
               related_scripts="02_reader_lag_check.sql"),
    sql_script("02", "02_reader_lag_check", "Checks this specific reader's lag via the Aurora-native cluster function.",
               sb.aurora_replica_status(),
               "Find this reader's server_id in the result set; unusually high lag specifically for this reader (compared to siblings) can itself cause query-side delays via recovery conflict handling.",
               related_scripts="../replication-lag/README.md"),
]

WORKFLOWS.append(_wf(
    slug="reader-lag-investigation",
    title="Reader Lag Deep-Dive Investigation",
    summary="A deeper, more structured investigation than replication-lag for cases where initial checks did not resolve the cause, walking through writer write-rate, storage I/O, and reader-side factors systematically.",
    symptoms=["replication-lag's initial checks did not identify a clear cause.", "Lag is intermittent/bursty rather than sustained, making correlation harder."],
    business_impact=["Same as replication-lag; this workflow exists for cases requiring a more systematic, multi-factor investigation."],
    root_causes=["A combination of factors (moderate write volume plus a moderately undersized reader) rather than one single dominant cause.", "Bursty batch/reporting workloads on the writer periodically spiking WAL generation."],
    investigation_strategy=["Re-confirm current lag levels across all readers.", "Correlate lag spikes against writer WAL generation over the same time window.", "Correlate lag spikes against checkpoint activity on the writer.", "Check for reader-side long-running queries at the same timestamps."],
    prerequisites=["Ability to correlate timestamps across writer and reader observations -- ideally via CloudWatch metrics correlation in addition to these SQL snapshots."],
    interpretation_guide=["Bursty lag correlating with periodic batch jobs (e.g. an hourly reporting query on the writer generating heavy WAL) points to a scheduling fix (move the batch job off-peak or to a reader) rather than a capacity fix."],
    remediation_immediate=["N/A -- deep-dive investigation, not an emergency workflow itself."],
    remediation_short_term=["Reschedule identified WAL-heavy batch jobs to lower-traffic windows."],
    remediation_long_term=["See replication-lag's long-term guidance."],
    production_safety=["Read-only."],
    escalation_criteria=["No clear pattern emerges after this deeper investigation -- open an AWS Support case with the gathered evidence."],
    related_issues=["../replication-lag/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_all_readers_lag_snapshot", "Snapshots lag across every reader in the cluster simultaneously for cross-reader comparison.",
               sb.aurora_replica_status(),
               "Compare lag across all readers at the same instant; uniform elevated lag across all readers points to a writer/cluster-wide cause, while an outlier reader points to an instance-specific cause.",
               related_scripts="02_writer_checkpoint_correlation.sql"),
    sql_script("02", "02_writer_checkpoint_correlation", "Checks writer checkpoint activity to correlate against lag spikes.",
               sb.checkpoint_activity(),
               "A high pct_forced_checkpoints occurring in the same window as observed lag spikes suggests checkpoint-driven WAL/I/O bursts as a contributing factor.",
               execution_location=WRITER_ONLY,
               related_scripts="../replication-lag/README.md"),
]

WORKFLOWS.append(_wf(
    slug="failover-investigation",
    title="Failover Investigation",
    summary="Post-hoc investigation of an Aurora failover event -- confirming it occurred, understanding its cause and timing, and assessing its impact, distinct from performance/performance-after-failover which focuses specifically on the post-failover cache-warmup performance dip.",
    symptoms=["Application experienced a brief connectivity disruption.", "AWS RDS/Aurora Events show a failover event.", "The writer instance identity has changed."],
    business_impact=["Understanding why a failover occurred (planned maintenance vs. an unplanned instance failure) determines whether follow-up action is needed and informs confidence in the platform's HA posture."],
    root_causes=["A planned failover (e.g. an AWS-initiated instance patch/maintenance, or a manually-triggered failover for testing/maintenance).", "An unplanned failover due to a writer instance failure/health-check failure detected by Aurora.", "A manually-triggered application-side failover test (see disaster-recovery/cluster-failover-drill)."],
    investigation_strategy=["Confirm current writer/reader roles and recent instance start times.", "Check AWS RDS Events (via AWS Console/CLI, not SQL) for the specific failover cause and timestamp.", "Assess connection/application impact during the failover window."],
    prerequisites=["AWS Console/CLI access to RDS/Aurora Events -- the failover cause itself is not visible via SQL."],
    interpretation_guide=["A recent pg_postmaster_start_time on the current writer combined with a corresponding AWS RDS Event is the clearest confirmation of a recent failover and its type (planned vs. unplanned)."],
    remediation_immediate=["If ongoing post-failover performance impact is present, see performance/performance-after-failover."],
    remediation_short_term=["If the failover was unplanned (instance failure), review CloudWatch/RDS Events for the underlying health-check failure reason and consider an AWS Support case if the cause is unclear."],
    remediation_long_term=["Use findings to inform disaster-recovery/cluster-failover-drill planning and application-side resiliency (connection retry/backoff) improvements."],
    production_safety=["SQL-side investigation is read-only; failover itself is an AWS-managed operation, not something triggered via SQL."],
    escalation_criteria=["An unplanned failover's root cause is not clear from RDS Events -- open an AWS Support case."],
    related_issues=["../failover-readiness/README.md", "../../performance/performance-after-failover/README.md", "../../disaster-recovery/cluster-failover-drill/README.md"],
    aurora_notes=["The failover mechanism itself, its trigger conditions, and its detailed cause are managed and recorded by the Aurora control plane and are visible via AWS RDS Events / CloudTrail / the Console, not via any PostgreSQL catalog -- SQL can only confirm the current role and instance start time from inside the database."],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_confirm_role_and_recent_restart", "Confirms current writer/reader role and how recently this instance started, as SQL-side evidence of a recent failover.",
               sb.cluster_recovery_role() + "\n\nSELECT pg_postmaster_start_time() AS instance_start_time,\n       now() - pg_postmaster_start_time() AS instance_uptime;",
               "A very recent instance_start_time on the current writer is consistent with a recent promotion; cross-reference the exact timestamp against AWS RDS Events for the definitive cause.",
               related_scripts="../../performance/performance-after-failover/README.md"),
]

WORKFLOWS.append(_wf(
    slug="failover-readiness",
    title="Failover Readiness Assessment",
    summary="Proactive assessment of whether the cluster and application are well-prepared for a failover, before one occurs -- covering reader fleet adequacy, application retry/backoff behavior, and connection endpoint usage.",
    symptoms=["No active symptom -- proactive readiness review, typically ahead of a planned maintenance window or as a standing operational practice."],
    business_impact=["Failover readiness directly determines how disruptive an inevitable future failover (planned or unplanned) will be to the business -- assessed and improved proactively, not discovered reactively during an actual incident."],
    root_causes=["N/A -- proactive assessment workflow."],
    investigation_strategy=["Confirm the application uses the cluster/reader endpoints correctly (not a hardcoded specific instance IP/hostname).", "Confirm at least one healthy reader exists to serve as failover target.", "Confirm application-side connection retry/backoff behavior is documented and tested."],
    prerequisites=["Access to application connection-string/endpoint configuration for review."],
    interpretation_guide=["An application connecting via a specific instance's endpoint/IP rather than the cluster (writer) endpoint will NOT automatically follow a failover and will experience an extended outage until manually reconfigured -- this is the single most critical readiness check."],
    remediation_immediate=["N/A."],
    remediation_short_term=["Fix any application connecting via a hardcoded instance endpoint instead of the cluster/reader endpoint immediately -- this is a readiness gap, not just an optimization."],
    remediation_long_term=["Schedule regular failover drills (see disaster-recovery/cluster-failover-drill) to validate readiness empirically, not just via configuration review."],
    production_safety=["This is a review/assessment workflow; the SQL scripts here are read-only."],
    escalation_criteria=["A business-critical service is found connecting via a hardcoded instance endpoint -- escalate to that service's owning team immediately as a standing availability risk."],
    related_issues=["../failover-investigation/README.md", "../../disaster-recovery/cluster-failover-drill/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_current_cluster_topology", "Confirms current writer/reader role for the connection being tested, to be run against each endpoint your applications actually use.",
               sb.cluster_recovery_role(),
               "Run this against the writer/cluster endpoint AND the reader endpoint your applications use; confirm each resolves to the role you expect. If an application's configured endpoint resolves to a specific instance rather than a cluster/reader endpoint, this is a readiness gap.",
               related_scripts="../../disaster-recovery/cluster-failover-drill/README.md"),
]

WORKFLOWS.append(_wf(
    slug="writer-reader-imbalance",
    title="Writer/Reader Load Imbalance",
    summary="Investigates whether read traffic is effectively distributed across the reader fleet, or whether load is concentrated on the writer (under-utilizing readers) or unevenly distributed across readers.",
    symptoms=["Writer CPU/load elevated while readers show low utilization.", "One reader shows much higher load than its siblings despite similar instance classes."],
    business_impact=["Failing to offload eligible read traffic to readers wastes provisioned reader capacity while unnecessarily loading the writer, which also serves all write traffic and cannot be scaled out horizontally the way readers can."],
    root_causes=["Application not using the reader endpoint for read-only queries at all (all traffic hardcoded to the writer/cluster endpoint).", "A custom query router unevenly distributing traffic across readers.", "A specific read-heavy feature routed to the writer for read-after-write consistency reasons, which is legitimate but should be a deliberate, documented choice, not a default."],
    investigation_strategy=["Compare session/query load on the writer vs. each reader.", "Confirm application read/write query routing configuration.", "For any read traffic deliberately routed to the writer, confirm the reasoning (consistency requirement) is documented."],
    prerequisites=["Direct connection access to writer and each reader for comparison."],
    interpretation_guide=["Some read traffic legitimately belongs on the writer (strict read-after-write requirements); the goal is intentional, documented routing, not zero writer reads."],
    remediation_immediate=["N/A."],
    remediation_short_term=["Update application data-access layer to route eligible read-only queries to the reader endpoint."],
    remediation_long_term=["Establish a documented read/write routing policy per feature, balancing consistency requirements against writer load reduction."],
    production_safety=["Read-only investigation."],
    escalation_criteria=["A large fraction of read-eligible traffic is found on the writer with no consistency justification -- escalate to the owning application team for a routing fix."],
    related_issues=["../reader-performance/README.md", "../../performance/high-database-load/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_writer_query_type_breakdown", "Breaks down query activity on the writer by application to identify read-heavy traffic that could potentially be offloaded to readers.",
               sb.connections_by_application_and_user(),
               "Run this on the writer specifically; applications showing high active_count here that are known to be read-only candidates are your offloading opportunities -- confirm with the owning team whether their consistency requirements actually need the writer.",
               execution_location=WRITER_ONLY,
               related_scripts="../reader-performance/README.md"),
]

WORKFLOWS.append(_wf(
    slug="replication-health",
    title="Overall Replication Health Check",
    summary="A routine, holistic health check spanning Aurora reader lag, any external logical replication slots/subscribers, and replication-related configuration -- intended for regular health monitoring rather than active-incident response.",
    symptoms=["No active symptom -- routine health check, suitable for inclusion in database-health/daily-health-check."],
    business_impact=["Regular replication health checks catch a slowly degrading reader or a silently stalled logical replication slot before it becomes a customer-visible incident."],
    root_causes=["N/A -- monitoring workflow."],
    investigation_strategy=["Check Aurora reader lag across the fleet.", "Check all replication slots (physical and logical) for active status and retained WAL.", "Check standard streaming replication for any external consumers."],
    prerequisites=["pg_monitor role membership."],
    interpretation_guide=["A healthy state is: all readers reporting low, stable lag via aurora_replica_status(); every replication slot either active=true or explicitly and knowingly retained for a documented reason; no unexpectedly large retained WAL."],
    remediation_immediate=["N/A -- pivot to the specific workflow (replication-lag, xid-wraparound-risk if a slot is pinning vacuum) matching any finding."],
    remediation_short_term=["N/A."],
    remediation_long_term=["Include this check in the standing automation/health-checks schedule."],
    production_safety=["Read-only."],
    escalation_criteria=["An inactive replication slot with significant retained WAL and no known owner -- escalate before dropping it (see transactions-and-xid/xid-wraparound-risk's slot-handling guidance)."],
    related_issues=["../replication-lag/README.md", "../../database-health/daily-health-check/README.md", "../../transactions-and-xid/xid-wraparound-risk/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_aurora_reader_lag_fleet_check", "Fleet-wide Aurora reader lag check.",
               sb.aurora_replica_status(),
               "All readers should show low, stable lag; investigate any outlier per replication-lag.",
               related_scripts="02_replication_slots_health.sql"),
    sql_script("02", "02_replication_slots_health", "Checks all replication slots for active status and retained WAL as part of the routine health check.",
               sb.replication_slots_and_wal_retention(),
               "Any slot with active = false and a large/growing retained WAL size needs immediate follow-up -- it is both a storage-growth risk and a vacuum-horizon risk.",
               related_scripts="../../transactions-and-xid/xid-wraparound-risk/scripts/08_replication_slots_xmin_pinning.sql"),
]
