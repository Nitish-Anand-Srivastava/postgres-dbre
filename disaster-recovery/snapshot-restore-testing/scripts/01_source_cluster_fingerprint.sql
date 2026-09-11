/*
===============================================================================
SCRIPT NAME:
01_source_cluster_fingerprint.sql

PURPOSE:
Fingerprints the source cluster immediately before the snapshot restore test: object inventory, per-table row estimates and sizes, extensions, and key settings.

AURORA POSTGRESQL VERSION:
Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise)

EXECUTION LOCATION:
Writer instance only (the query reads/writes state that only exists or is meaningful on the writer)

SAFETY:
READ ONLY

EXPECTED IMPACT:
Minimal -- reads system catalogs/statistics views only, no table locks beyond a brief catalog lookup.

REQUIRED PRIVILEGES:
Role membership in `pg_monitor` (or `pg_read_all_stats`) is sufficient. No superuser required.

PREREQUISITES:
None beyond CONNECT on the target database.

EXECUTION ORDER:
Step 01 of workflow 'disaster-recovery/snapshot-restore-testing'

RELATED SCRIPTS:
02_restored_cluster_validation.sql, 03_snapshot_restore_runbook.md

HOW TO INTERPRET RESULTS:
Save all four result sets verbatim as the pre-restore fingerprint, together with the exact time they were captured -- the capture time is what explains legitimate differences later, since the snapshot represents a moment that is almost never identical to the fingerprint moment. Pay particular attention to the extension inventory and key settings: these are the two areas where a restored cluster most often differs from its source through configuration rather than data, because the restore takes the parameter group you specify rather than inheriting the source's.
===============================================================================
*/

-- Object inventory for the current database. Compare this against the same
-- query on the restored cluster -- a missing relation or a materially
-- different count is the finding a restore test exists to surface.
SELECT
    count(*) FILTER (WHERE c.relkind IN ('r', 'p'))              AS table_count,
    count(*) FILTER (WHERE c.relkind = 'i')                      AS index_count,
    count(*) FILTER (WHERE c.relkind = 'm')                      AS matview_count,
    count(*) FILTER (WHERE c.relkind = 'S')                      AS sequence_count,
    count(DISTINCT n.nspname)                                    AS schema_count,
    pg_size_pretty(pg_database_size(current_database()))         AS database_size
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema');

-- Per-table row estimates and sizes, largest first. reltuples is an
-- estimate maintained by vacuum/analyze rather than an exact count, which
-- is exactly what is wanted here: it is cheap on a very large cluster and
-- precise enough for a source-versus-restored comparison.
\set top_n 50
SELECT
    n.nspname                                                    AS schema_name,
    c.relname                                                    AS table_name,
    c.reltuples::bigint                                          AS estimated_rows,
    pg_size_pretty(pg_total_relation_size(c.oid))                AS total_size,
    pg_total_relation_size(c.oid)                                AS total_bytes
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY pg_total_relation_size(c.oid) DESC
LIMIT :top_n;

-- Extensions currently installed in this database vs. what Aurora
-- PostgreSQL makes available. Many investigation scripts in this toolkit
-- depend on pg_stat_statements (query stats) and/or pgstattuple (exact
-- bloat); confirm both are available/installed before relying on those
-- scripts.
SELECT
    e.extname,
    e.extversion,
    n.nspname                                                   AS installed_schema
FROM pg_extension e
JOIN pg_namespace n ON n.oid = e.extnamespace
ORDER BY e.extname;

-- Snapshot of the settings that most commonly explain performance and
-- concurrency behavior differences between environments. On Aurora, most of
-- these are controlled by the DB cluster parameter group (values shared by
-- all instances) or the DB instance parameter group (writer/reader-specific
-- overrides), not postgresql.conf -- use the AWS Console/CLI
-- (describe-db-cluster-parameters / describe-db-parameters) to change them,
-- not ALTER SYSTEM, which Aurora does not support for most parameters.
SELECT
    name,
    setting,
    unit,
    category,
    short_desc,
    context
FROM pg_settings
WHERE name IN (
    'max_connections', 'shared_buffers', 'work_mem', 'maintenance_work_mem',
    'effective_cache_size', 'autovacuum', 'autovacuum_max_workers',
    'autovacuum_naptime', 'autovacuum_vacuum_cost_limit',
    'autovacuum_freeze_max_age', 'autovacuum_multixact_freeze_max_age',
    'checkpoint_timeout', 'max_wal_size', 'statement_timeout',
    'idle_in_transaction_session_timeout', 'lock_timeout',
    'log_lock_waits', 'deadlock_timeout', 'track_io_timing',
    'shared_preload_libraries', 'random_page_cost', 'effective_io_concurrency'
)
ORDER BY name;
