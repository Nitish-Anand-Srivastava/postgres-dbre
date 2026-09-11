# 04_access_anomaly_containment_runbook

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `04_access_anomaly_containment_runbook.md` |
| Purpose | Guarded containment runbook: preserve evidence, block new connections for an implicated role, terminate its sessions, revoke over-broad grants, and hand off to the AWS-side investigation. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance preferred; safe to run on a reader but results reflect only that reader's local activity |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | Step 1 blocks all new connections for the role, including legitimate ones. Step 2 aborts in-flight transactions for the terminated sessions. Step 3 changes access for every role covered by the revoked grant, not only the implicated one. Each step is disruptive by design and must be a recorded decision. |
| Required privileges | CREATEROLE (or rds_superuser) to alter the role; `pg_signal_backend` membership (or rds_superuser) to terminate another role's backends; ownership of the object, or rds_superuser, to revoke its grants. |
| Prerequisites | Scripts 01-03 completed and their output saved to the incident record with capture times; security incident response engaged; the availability impact of containment agreed with the owning application team. |
| Execution order | Step 04 of workflow `security-and-access/access-anomaly-investigation` |
| Related scripts | 01_current_sessions_by_identity_and_origin.sql, 03_privilege_escalation_surface.sql |

## How to interpret / use this runbook

Work strictly top to bottom: capture, notify, block new connections, terminate by explicit pid, revoke narrowly, rotate, then close the network path. The most common and most costly mistake in this runbook is starting at the termination step because it feels like the decisive action -- it is the step that permanently removes the evidence every subsequent question depends on.

---

## Order of operations (do not reorder)

Containment destroys evidence. Every step below assumes the previous one is complete and its output is saved to the incident record with the capture time.

1. Capture: run `01_current_sessions_by_identity_and_origin.sql`, `02_sessions_outside_expected_access_model.sql`, and `03_privilege_escalation_surface.sql`, saving all output.
2. Notify: engage security incident response and the owning application team before cutting access, unless active exfiltration is in progress.
3. Contain (this runbook).
4. Correlate AWS-side: CloudWatch Logs (if `log_connections` was enabled), CloudTrail (for IAM-authenticated connections and any RDS API activity), and VPC flow logs for the client address captured in step 1.

## Step 1 -- block new connections for the implicated role

Do this *before* terminating sessions. Terminating first simply frees the client to reconnect into the gap, and you will have destroyed the session evidence for nothing:

```sql
ALTER ROLE compromised_svc NOLOGIN;
```

Rollback: `ALTER ROLE compromised_svc LOGIN;`. Be explicit with the application owner about what else uses this role -- if it is shared with production traffic, this step is an availability decision as much as a security one, and it must be a recorded, joint decision rather than a unilateral one.

## Step 2 -- terminate the implicated sessions

Terminate by explicit pid, taken from script 01's captured output -- never by a broad predicate, which will sweep up legitimate sessions in the same statement:

```sql
SELECT pg_terminate_backend(12345);
```

`pg_terminate_backend()` rolls back the session's in-flight transaction. For an ordinary read that is harmless; if the session was mid-write, the rollback is the correct outcome but the application on the other end will see an error, so confirm which pids you are terminating rather than pasting a list.

There is no rollback for a terminated session. The client may reconnect unless Step 1 has already been applied -- which is exactly why Step 1 comes first.

## Step 3 -- revoke over-broad grants identified in script 03

Revoke the narrowest grant that closes the exposure, and record the exact grant text before revoking it -- the grant is itself evidence of how access was obtained:

```sql
REVOKE SELECT ON public.wallets FROM PUBLIC;
```

```sql
REVOKE GRANT OPTION FOR SELECT ON public.ledger_entries FROM reporting_ro;
```

Rollback: re-issue the equivalent `GRANT` (including `WITH GRANT OPTION` where it applied). Before revoking anything from PUBLIC, confirm no legitimate role depends on it -- a PUBLIC grant that has existed for years may be the only access path a reporting job has, and revoking it during an incident adds a second outage to the first.

## Step 4 -- rotate credentials

Rotate every credential that could plausibly have been exposed, not only the one observed in use, following the dual-credential pattern in `credential-and-authentication-hygiene/scripts/03_credential_rotation_and_hardening.md`. A role left at `NOLOGIN` is contained but broken; rotation plus re-enabling is what restores service safely.

## Step 5 -- close the network path (AWS side, not SQL)

If the client address captured in script 01 was outside the intended application tier, the durable fix is the security group, not the database. Review the cluster's inbound rules and remove any range broader than the application tier requires; this is a change-managed AWS action and should be reviewed by both the platform and security owners.

## Do NOT

- Do NOT terminate sessions before capturing scripts 01-03; the session inventory exists nowhere else once those backends exit.
- Do NOT `REVOKE` broadly to 'be safe' during an incident -- an over-broad revoke on a shared table causes an application outage that will be attributed to the attacker and will consume the response team's attention.
- Do NOT drop the implicated role. Dropping it destroys its ownership and grant history, which the post-incident review and any regulator-facing report will need; `NOLOGIN` contains it just as effectively.
- Do NOT conclude the investigation from in-database data alone -- PostgreSQL retains no per-session access history by default, so the AWS-side correlation in step 4 of the order of operations is not optional.
