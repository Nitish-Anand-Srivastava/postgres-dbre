# Scripts: Comprehensive Aurora PostgreSQL HTML Observability Report

Execution order, safety classification, and expected runtime for every script
in `observability/comprehensive-html-report/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_postgres_observability_report.sql` | Complete Aurora PostgreSQL observability snapshot rendered as a local HTML file. | LOW RISK WRITE (session-scoped temporary table only) | Typically seconds to several minutes; run once and avoid repeated execution during peak load. |

## Execution Order

Run scripts strictly in the numeric order shown above. Each script assumes the
operator has reviewed the output of the prior step. Do not skip ahead to a
remediation template (`.md` files, if present) without completing the
numbered investigation steps first.

## Platform-specific execution

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


## Required Permissions

Unless a script states otherwise in its `REQUIRED PRIVILEGES` header field, a
role with the built-in `pg_monitor` (or `pg_read_all_stats` /
`pg_read_all_settings`) attribute, `CONNECT` on the target database, and
`USAGE` on `public` is sufficient. Scripts that read `pg_stat_statements`
require that extension to be installed in the current database. Scripts that
touch DDL, `pg_terminate_backend()`, or write operations state elevated
requirements explicitly in their own header.

## Expected Output

The command writes a self-contained `postgres_observability_report.html` file. Open it locally in a modern browser and begin with the executive summary and prioritized findings. The file can contain database names, roles, schema metadata, and query text; handle it as production operational evidence rather than a public artifact.

## When to Stop and Escalate

- Any critical finding that affects availability, transaction ID safety, replication, or connection headroom is confirmed by the corresponding focused workflow.
- The report cannot complete with the documented role because required catalog visibility is restricted; involve the database platform owner rather than broadening privileges ad hoc.
- Runtime or load is materially higher than the documented range; stop repeated runs and use narrower scripts while investigating the cause.

## Scripts That Should Not Be Run During Severe Incidents

_This report is LOW RISK WRITE because it uses a session-scoped temporary table, and its broad catalog/statistics scan can add avoidable load. During a severe incident, prefer the narrow symptom-specific scripts first; run the comprehensive report once only when the instance has sufficient headroom._
