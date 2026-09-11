# Investigation Methodology

This page defines the methodology every workflow directory in this
repository follows. If you are responding to an incident, read this once;
after that, the parent `README.md` of the relevant workflow (e.g.
`performance/slow-queries/README.md`) will apply this methodology to the
specific problem you are facing.

## 1. The core loop: broad → narrow → root cause → remediation

Every workflow is a sequence of numbered scripts designed to be run **in
order**, each one narrowing the search space based on what the previous
step revealed:

```text
 01  Broad system state          "Is anything obviously wrong right now?"
      │
 02  Narrow to the affected       "Which database / session / query / table?"
      scope
      │
 03  Correlate contributing       "Locks? Waits? Vacuum? Storage? Plan change?"
      factors
      │
 04  Confirm root cause           "What is actually causing the symptom?"
      │
 05  Remediation guidance         "What do I do about it, and what's the risk?"
```

This is why scripts are numbered and why the numbering is part of the
contract (see `CONTRIBUTING.md`): running them out of order tends to
either miss context that a later script depends on, or waste time
re-deriving something an earlier script already established.

## 2. Directory-first navigation

The repository is organized by **operational problem**, not by PostgreSQL
feature. When responding to an incident:

1. Identify the problem category (performance, locking, vacuum, storage,
   replication, etc.) from the root `README.md` navigation tree.
2. Open that category directory.
3. Pick the specific workflow that matches the symptom (e.g.
   `performance/high-cpu/` vs. `performance/slow-queries/`).
4. Read that workflow's `README.md` in full before running anything --
   it defines symptoms, business impact, and escalation criteria specific
   to that problem, which changes how you interpret script output.
5. Run `scripts/` in numeric order, using `scripts/README.md` as the
   execution/safety reference table.

You should not need to jump between unrelated categories to complete a
single investigation. Some duplication of similar-looking queries across
workflows is intentional (see `CONTRIBUTING.md` -- duplication over
coupling).

## 3. Reading results, not just running scripts

Each script's header contains a `HOW TO INTERPRET RESULTS` field, and each
workflow README contains a "Interpretation Guide" section. Do not treat
script output as self-explanatory:

* A non-zero value is not automatically a problem (e.g., `idx_scan = 0` on
  a young table, or a handful of `idle in transaction` sessions during
  normal connection pool churn).
* Absolute numbers matter less than **trend and comparison**: compare
  against the same query run during a known-good baseline period, not
  against an assumed universal threshold.
* Aurora-specific caveats apply to some standard views (see
  `docs/aurora-postgresql/README.md`); do not port thresholds or
  interpretations directly from self-managed PostgreSQL tribal knowledge
  without checking whether they still apply.

## 4. Escalation is part of the methodology

Every workflow README defines explicit escalation criteria (to application
engineering, infrastructure/SRE, AWS Support, or database engineering
leadership). Investigation is not expected to always end with a DBA-only
fix -- knowing when to stop investigating and escalate is itself part of
the Staff DBA skill this repository encodes. Escalate immediately, without
finishing every script, if:

* The affected system is on a financial write path (order matching,
  ledger, balance updates, withdrawals) and the safe investigation window
  is closing.
* A script's own header or the workflow README flags a step as
  "do not run during severe incidents" and you are in a severe incident.
* Root cause appears to be outside PostgreSQL entirely (network, EC2/ECS
  compute, application bug, upstream dependency).

## 5. From investigation to remediation

Investigation workflows in this repository intentionally separate:

* **Immediate mitigation** -- safe to do now, buys time, rarely
  irreversible (e.g., adjusting a connection pool limit, cancelling one
  identified runaway query with operator confirmation).
* **Short-term remediation** -- addresses the immediate cause but is not
  the permanent fix (e.g., manually running `ANALYZE` on one table whose
  statistics are stale).
* **Long-term engineering fix** -- schema change, application change,
  capacity change, or process change that prevents recurrence.

Never skip straight to a destructive or high-risk remediation without
completing the read-only investigation steps and understanding blast
radius -- see `docs/production-safety/README.md`.

## 6. Related reading

* `docs/production-safety/README.md` -- the safety model this methodology
  assumes.
* `docs/prerequisites/README.md` and `docs/permissions/README.md` -- what
  you need before you can execute the methodology at all.
* `docs/glossary/README.md` -- terminology used throughout workflow
  READMEs and script headers.
