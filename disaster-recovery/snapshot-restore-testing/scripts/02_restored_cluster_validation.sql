/*
===============================================================================
SCRIPT NAME:
02_restored_cluster_validation.sql

PURPOSE:
Run on the restored scratch cluster: repeats the source fingerprint and adds engine identity and instance role, for a direct comparison against script 01.

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
Run against the restored scratch cluster, after at least one DB instance has been provisioned in it and is available. Script 01 must already have been run and saved on the source cluster.

EXECUTION ORDER:
Step 02 of workflow 'disaster-recovery/snapshot-restore-testing'

RELATED SCRIPTS:
01_source_cluster_fingerprint.sql, 04_restore_test_checklist.md

HOW TO INTERPRET RESULTS:
Compare each result set against script 01's saved output from the source cluster. Object counts and per-table row estimates should match within the drift explained by writes between the snapshot and the source fingerprint -- a table missing entirely, or an estimate off by an order of magnitude, is a genuine finding. A settings difference almost always means the restore used a different (often default) parameter group, which must be corrected before any performance comparison or before the restored cluster is considered a viable recovery target. A missing extension means the restored cluster cannot run the parts of this toolkit or the application that depend on it. Ignore differences in pg_stat_database counters: statistics start fresh on a restored cluster and prove nothing either way.
===============================================================================
*/

-- Run this against the RESTORED scratch cluster, not production. It repeats
-- script 01's fingerprint and adds the engine identity and instance role,
-- so the comparison covers "is it the same data" and "is it the same
-- engine and configuration" together.
SELECT
    current_database()                                           AS database_name,
    current_setting('server_version')                            AS server_version,
    pg_is_in_recovery()                                          AS is_reader_instance,
    pg_postmaster_start_time()                                   AS instance_start_time,
    now() - pg_postmaster_start_time()                           AS instance_uptime,
    clock_timestamp()                                            AS validated_at;

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

-- Any index left INVALID by an interrupted build on the source cluster is
-- restored in that same invalid state -- worth catching here rather than
-- discovering it in a recovery that depended on the index existing.
SELECT
    n.nspname                                                    AS schema_name,
    t.relname                                                    AS table_name,
    i.relname                                                    AS index_name,
    ix.indisvalid                                                AS is_valid,
    ix.indisready                                                AS is_ready
FROM pg_index ix
JOIN pg_class i ON i.oid = ix.indexrelid
JOIN pg_class t ON t.oid = ix.indrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
WHERE NOT ix.indisvalid
   OR NOT ix.indisready
ORDER BY n.nspname, t.relname, i.relname;

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
