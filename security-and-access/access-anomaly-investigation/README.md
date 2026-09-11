# Access Anomaly Investigation

**Category:** Security and Access | **Workflow:** `security-and-access/access-anomaly-investigation`

## 1. Problem Description

The reactive workflow for 'someone or something is connecting to this database that should not be' -- establishing, from catalog and live-activity data alone, who is currently connected, from where, over what transport, with what privileges, and which of those facts is inconsistent with the documented access model.

## 2. Typical Symptoms

- Connections appear from a client address, application_name, or role that is not part of the documented access model for this cluster.
- A security alert (from CloudTrail, a network flow log, a secret-scanning hit, or an intrusion-detection system) points at this database and needs corroboration from inside it.
- A role's connection count, query pattern, or connecting host changes abruptly with no corresponding deploy or scheduled job.
- A privilege that nobody on the team remembers granting appears in a routine role-and-privilege-audit.

## 3. Business Impact

- Unauthorized read access to wallet balances, deposit addresses, ledger entries, or order-book state is a direct customer-data breach with regulatory reporting obligations, and on an exchange it is also directly monetizable by the attacker -- front-running visible order flow or mapping customer holdings -- so the window between detection and containment has immediate financial consequence, not only compliance ones.
- Investigating without a disciplined sequence destroys the evidence needed afterward: terminating sessions before capturing their identity, or revoking grants before recording them, makes the regulator-facing question 'what was accessed and by whom' permanently unanswerable.

## 4. Possible Root Causes

- A leaked or shared static credential is being used from outside the expected network path (see credential-and-authentication-hygiene).
- A security group, subnet route, or VPC peering change widened network reachability to the cluster beyond the intended application tier.
- A legitimate but undocumented integration (an analytics tool, a vendor connector, a colleague's local psql session) is connecting directly to production, which looks identical to an attack from inside the database.
- An over-broad grant -- often to PUBLIC or to a widely-held group role -- lets an existing, legitimate low-privilege role reach data it was never meant to see, so nothing about the *connection* is anomalous, only the access (see public-schema-exposure).
- A role obtained escalation through a grantable privilege (`WITH GRANT OPTION`) or the CREATEROLE attribute and granted itself further access.

## 5. Investigation Strategy

1. Capture the current connection picture first -- role, client address, application name, backend start time, state, and SSL status -- because pg_stat_activity is a live snapshot that is gone the moment those sessions end.
2. Classify each session against the documented expectation (expected roles, expected client network) so anomalies are flagged by the query rather than spotted by eye under pressure.
3. Enumerate the standing escalation surface: roles with elevated attributes, grantable privileges, and objects reachable via PUBLIC -- this answers 'what could the anomalous identity have reached', which matters more than what it happened to run.
4. Only then decide on containment, following the guarded runbook so evidence is preserved before access is cut.

## 6. Prerequisites

- `pg_monitor` membership so `pg_stat_activity` shows the query text, client address, and state of *other* roles' sessions -- without it, rows for other users are largely masked and the investigation will silently under-report.
- The documented list of expected application roles and expected client network ranges for this cluster; without it, script 02 cannot distinguish anomalous from normal and will simply flag everything.
- Awareness that in-database data alone cannot prove intent or reconstruct history -- correlate with the AWS-side and log-side sources (`log_connections` output, CloudTrail, VPC flow logs) referenced in this workflow.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_current_sessions_by_identity_and_origin.sql`](scripts/01_current_sessions_by_identity_and_origin.sql) -- Captures the live session inventory -- role, client address, application, transport encryption, state, and age -- as the first evidence step of an access investigation.
2. [`scripts/02_sessions_outside_expected_access_model.sql`](scripts/02_sessions_outside_expected_access_model.sql) -- Classifies every live session against a configurable list of expected roles and an expected client network range, so sessions inconsistent with the documented access model sort to the top.
3. [`scripts/03_privilege_escalation_surface.sql`](scripts/03_privilege_escalation_surface.sql) -- Enumerates the standing escalation surface -- elevated role attributes, re-grantable privileges, and objects reachable by every role via PUBLIC -- to answer what an implicated identity could have reached.
4. [`scripts/04_access_anomaly_containment_runbook.md`](scripts/04_access_anomaly_containment_runbook.md) -- Guarded containment runbook: preserve evidence, block new connections for an implicated role, terminate its sessions, revoke over-broad grants, and hand off to the AWS-side investigation.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Aurora has no `pg_hba.conf` to inspect for which hosts are permitted: network reachability is governed by the cluster's VPC security groups and subnet routing, and authentication method availability by the parameter group and IAM configuration -- so the 'where could this connection have come from' half of the investigation happens in the AWS console/API, not in SQL.
- Connection-level audit history on Aurora comes from `log_connections`/`log_disconnections` in the parameter group (published to CloudWatch Logs when log export is enabled) and, for IAM-authenticated connections, from CloudTrail -- none of it is queryable from inside PostgreSQL, so capture the in-database snapshot here and correlate it with those sources rather than expecting SQL to answer the historical question.
- Because Aurora readers share the same storage and the same role definitions as the writer, an anomalous identity has the same data access on every instance in the cluster; checking only the writer's `pg_stat_activity` will miss sessions attached to a reader, so run script 01 against each instance endpoint, not just the cluster writer endpoint.

## 8. Interpretation Guide

- `client_addr IS NULL` means the connection did not arrive over TCP from an external client -- on Aurora this is characteristic of internal/management activity rather than an application, so treat it as a category to explain, not automatically as an intrusion.
- A session whose `usename` is outside the expected role list, *or* whose `client_addr` is outside the expected network range, is the primary signal from script 02; a session that is anomalous on both counts simultaneously is the highest priority row in the entire workflow.
- `ssl = false` on an anomalous session is doubly significant: the traffic is readable on the network path, and it indicates a client configured outside the standard application connection template (see ssl-and-connection-security).
- A generic or absent `application_name` on a long-lived session from an unexpected address is a meaningful signal -- every first-party service on a well-run platform sets a recognizable application_name, so its absence points at an ad hoc client rather than a deployed service.
- In the escalation-surface result, `is_grantable = true` means the grantee can re-grant that privilege to anyone else, so a single such row can explain a privilege that 'nobody granted'; `rolcreaterole = true` is the strongest standing escalation path short of rds_superuser membership, since a role that can create roles can create one with privileges it will then grant itself.
- Absence of evidence is not evidence of absence here: `pg_stat_activity` shows only sessions that exist right now, and `pg_stat_statements` aggregates by statement rather than by session identity, so neither can tell you what a session that already disconnected did.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Capture evidence before cutting access: save the output of scripts 01-03 (with timestamps) to the incident record first -- terminating a session erases the only in-database record of it.
- If containment cannot wait, block new connections for the implicated role (`ALTER ROLE ... NOLOGIN`) before terminating its existing sessions, otherwise the client simply reconnects into the gap; both steps are in the guarded containment runbook.
- Engage security incident response in parallel with, not after, the database-side work -- the network and IAM side of the investigation runs concurrently and needs the connection details captured in script 01.

**Short-term remediation** (hours to days):

- Rotate every credential that could plausibly have been exposed, using the dual-credential pattern in credential-and-authentication-hygiene, not just the one credential confirmed to have been used.
- Revoke the specific over-broad grants identified in script 03, starting with anything granted to PUBLIC on tables holding customer or financial data.
- Enable `log_connections`/`log_disconnections` if they were off, so the next investigation has an authentication history rather than only a live snapshot.

**Long-term engineering fix** (days to weeks):

- Close the network path: restrict the cluster's security groups to the application tier, and remove any direct human/tool access path to the production writer in favor of a controlled read path against a reader.
- Adopt IAM database authentication for service roles so there is no static credential to leak, and so every connection is attributable to an AWS identity in CloudTrail (see audit-logging-and-iam-auth).
- Install pgaudit if the platform is subject to an access-attribution requirement -- this workflow's fundamental limitation is that PostgreSQL does not retain per-session access history by default, and no catalog query can recover it after the fact.
- Fold the escalation-surface query (script 03) into the scheduled security review so grantable privileges and CREATEROLE attributes are noticed on a cadence rather than during an incident.

## 10. Production Safety

- Scripts 01-03 are read-only catalog and statistics queries, safe to run on a production writer during an active incident, and they are the correct first action -- they gather exactly the evidence that containment destroys.
- No script in this workflow terminates a session or changes a privilege. Containment actions -- `NOLOGIN`, `pg_terminate_backend()`, `REVOKE` -- live only in the guarded runbook (script 04), because each is disruptive to legitimate traffic on the same role and irreversible with respect to the evidence it removes.
- Treat the output of these scripts as incident evidence: store it with the incident record, with the capture time recorded, rather than pasting it into an ephemeral chat thread.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Any session is confirmed as an identity that is not part of the documented access model -- escalate to security incident response immediately; do not attempt to resolve it as a database-only issue.
- A role with access to wallet, ledger, deposit, or withdrawal tables is implicated -- escalate to security and compliance leadership the same hour, since customer-data-breach notification timelines may start at the point of detection.
- The escalation-surface query shows a privilege grant or role attribute that nobody can account for -- escalate rather than revoking it silently, because the grant itself is evidence of how the access was obtained.
- Containment would require terminating sessions belonging to a shared role that also serves production traffic -- escalate for a joint decision with the application owner; the availability impact of containment must be an explicit, recorded choice.

## 12. Related Issues

- [role-and-privilege-audit](../role-and-privilege-audit/README.md)
- [credential-and-authentication-hygiene](../credential-and-authentication-hygiene/README.md)
- [ssl-and-connection-security](../ssl-and-connection-security/README.md)
- [row-level-security-review](../row-level-security-review/README.md)
- [connection-exhaustion](../../connections/connection-exhaustion/README.md)
